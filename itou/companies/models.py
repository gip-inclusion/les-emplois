import sys
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.gis.measure import D
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import BooleanField, Case, Count, Exists, F, OuterRef, Q, Subquery, Value, When
from django.db.models.constraints import UniqueConstraint
from django.db.models.functions import Cast, Coalesce, Greatest
from django.urls import reverse
from django.utils import timezone

from itou.common_apps.address.models import AddressMixin
from itou.common_apps.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationQuerySet
from itou.companies.enums import (
    POLE_EMPLOI_SIRET,
    CompanyKind,
    ContractType,
    JobDescriptionSource,
    JobSource,
    JobSourceTag,
)
from itou.users.enums import UserKind
from itou.utils.emails import get_email_message
from itou.utils.tokens import company_signup_token_generator
from itou.utils.triggers import FieldsHistory
from itou.utils.urls import get_absolute_url, get_tally_form_url
from itou.utils.validators import validate_af_number, validate_naf, validate_siret


class CompanyQuerySet(OrganizationQuerySet):
    @property
    def active_lookup(self):
        # Prefer a sub query to a join for performance reasons.
        # See `self.with_count_recent_received_job_apps`.
        has_active_convention = Exists(SiaeConvention.objects.filter(id=OuterRef("convention_id"), is_active=True))
        return (
            # GEIQ, EA, EATT, ... have no convention logic and thus are always active.
            # `~` means NOT, similarly to dataframes.
            ~Q(kind__in=CompanyKind.siae_kinds())
            # Staff created companiess are always active until eventually
            # converted to ASP source companies by import_siae script.
            # Such companies are created by our staff when ASP data is lacking
            # the most recent data about them.
            | Q(source=Company.SOURCE_STAFF_CREATED)
            # ASP source companies and user created companies are active if and only
            # if they have an active convention.
            | has_active_convention
            # Exclude POLE EMPLOI specifically since it is there to be linked with
            # external PEC offers (time of writing) but should not be selected or
            # specifically searchable.
        )

    def with_has_convention_in_grace_period(self):
        now = timezone.now()
        grace_period = timezone.timedelta(days=SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)
        # Prefer a sub query to a join for performance reasons.
        # See `self.with_count_recent_received_job_apps`.
        has_convention_in_grace_period = Exists(
            SiaeConvention.objects.filter(id=OuterRef("convention_id"), deactivated_at__gte=now - grace_period)
        )
        return self.annotate(has_convention_in_grace_period=has_convention_in_grace_period)

    def active(self):
        return self.filter(self.active_lookup)

    def active_or_in_grace_period(self):
        return self.with_has_convention_in_grace_period().filter(
            self.active_lookup
            # Include siaes experiencing their grace period.
            | Q(has_convention_in_grace_period=True)
        )

    def within(self, point, distance_km):
        return self.filter(coords__dwithin=(point, D(km=distance_km)))

    def with_count_recent_received_job_apps(self):
        """
        Count the number of recently received job applications.

        The count with a `Subquery` instead of a `join` is way more efficient here.
        We generate this SQL using the Django ORM:

        SELECT
            *,
            COALESCE((
                SELECT COUNT(U0."id") AS "count"
                FROM "job_applications_jobapplication" U0
                WHERE (
                    U0."created_at" >= 2021-06-10 08:45:51.998244 + 00:00
                    AND U0."to_company_id" = "companies_company"."id"
                )
                GROUP BY U0."to_company_id"), 0) AS "count_recent_received_job_apps"
        FROM
            "companies_company"

        See https://github.com/martsberger/django-sql-utils
        """
        # Avoid a circular import
        job_application_model = self.model._meta.get_field("jobapplication").related_model

        sub_query = Subquery(
            (
                job_application_model.objects.filter(
                    to_company=OuterRef("id"),
                    created_at__gte=timezone.now()
                    - timezone.timedelta(weeks=job_application_model.WEEKS_BEFORE_CONSIDERED_OLD),
                )
                .values("to_company")  # group job apps by to_company
                .annotate(count=Count("pk"))
                .values("count")
            ),
            output_field=models.IntegerField(),
        )
        # `Coalesce` will return the first not null value or zero.
        return self.annotate(count_recent_received_job_apps=Coalesce(sub_query, 0))

    def with_count_active_job_descriptions(self):
        """
        Count the number of active job descriptions by SIAE.
        """
        # A subquery is way more efficient here than a join.
        # See `self.with_count_recent_received_job_apps`.
        sub_query = Subquery(
            (
                JobDescription.objects.filter(is_active=True, company=OuterRef("id"))
                .values("company")
                .annotate(count=Count("pk"))
                .values("count")
            ),
            output_field=models.IntegerField(),
        )
        return self.annotate(count_active_job_descriptions=Coalesce(sub_query, 0))

    def with_is_hiring(self):
        """
        A company is considered hiring if it is not blocking job applications and has at least
        one active job description or accepts spontaneous job applications.
        """
        return self.with_count_active_job_descriptions().annotate(
            is_hiring=Case(
                When(
                    Q(block_job_applications=False)
                    & (Q(count_active_job_descriptions__gt=0) | Q(spontaneous_applications_open_since__isnull=False)),
                    then=True,
                ),
                default=False,
                output_field=BooleanField(),
            )
        )

    def with_computed_job_app_score(self):
        """
        Employer search results continuously boost companies which did not receive enough recent job applications
        per job opening. In other words, we show on the first page the companies which have not received
        yet their fair share of recent job applications relative to others.

        What we call "jop opening" here is any active job description (0-n) and any spontaneous
        application opening (0-1). We strive to send approximately the same amount of applications per job
        opening. This means we strive to send 10 times more applications to a company with 10 job openings
        than to another company with just 1 job opening.

        Any hiring company will always by definition have at least 1 job opening (see `with_is_hiring`).
        Non hiring companies are still shown in later pages of the search results though, some of those
        have 0 job openings due to having no active job description and having closed spontaneous applications.
        To sort those companies by received applications anyway and avoid a division by zero error, we will
        arbitrarily consider that they have 1 job opening instead of 0.

        The following score is used:
        ** (total of recent job applications) / (total of job openings) **
        """
        # Transform integer into a float to avoid any weird side effect.
        # See self.with_count_recent_received_job_apps
        count_recent_received_job_apps = Cast("count_recent_received_job_apps", output_field=models.FloatField())

        # Transform integer into a float to avoid any weird side effect.
        # See self.with_count_active_job_descriptions
        count_active_job_descriptions = Cast("count_active_job_descriptions", output_field=models.FloatField())

        # Transform integer into a float to avoid any weird side effect.
        # This is either 0 (closed) or 1 (open).
        count_spontaneous_applications_open = Case(
            When(spontaneous_applications_open_since__isnull=False, then=Value(1.0)),
            default=Value(0.0),
            output_field=models.FloatField(),
        )

        count_job_openings = Cast(
            count_active_job_descriptions + count_spontaneous_applications_open, output_field=models.FloatField()
        )

        count_job_openings = Greatest(count_job_openings, Value(1.0))

        get_score = Cast(count_recent_received_job_apps / count_job_openings, output_field=models.FloatField())

        return (
            self.with_count_recent_received_job_apps()
            .with_count_active_job_descriptions()
            .annotate(computed_job_app_score=get_score)
        )

    def with_has_active_members(self):
        # Prefer a sub query to a join for performance reasons.
        # See `self.with_count_recent_received_job_apps`.
        return self.annotate(
            has_active_members=Exists(CompanyMembership.objects.active().filter(company=OuterRef("pk")))
        )


class CompanyManager(models.Manager.from_queryset(CompanyQuerySet)):
    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset().exclude(siret=POLE_EMPLOI_SIRET).defer("fields_history")


class CompanyUnfilteredManager(models.Manager.from_queryset(CompanyQuerySet)):
    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset().defer("fields_history")


class Company(AddressMixin, OrganizationAbstract):
    """
    Structures d'insertion par l'activité économique.

    To retrieve jobs of a company:
        self.jobs.all()             <QuerySet [<Appellation>, ...]>
        self.job_description_through.all()     <QuerySet [<JobDescription>, ...]>
    """

    SOURCE_ASP = "ASP"
    SOURCE_GEIQ = "GEIQ"
    SOURCE_EA_EATT = "EA_EATT"
    SOURCE_USER_CREATED = "USER_CREATED"
    SOURCE_STAFF_CREATED = "STAFF_CREATED"

    SOURCE_CHOICES = (
        (SOURCE_ASP, "Export ASP"),
        (SOURCE_GEIQ, "Export GEIQ"),
        (SOURCE_EA_EATT, "Export EA+EATT"),
        (SOURCE_USER_CREATED, "Utilisateur (Antenne)"),
        (SOURCE_STAFF_CREATED, "Staff Itou"),
    )

    # These kinds of Companies can use employee record app to send data to ASP
    ASP_EMPLOYEE_RECORD_KINDS = [CompanyKind.ACI, CompanyKind.AI, CompanyKind.EI, CompanyKind.EITI, CompanyKind.ETTI]

    # Large score by default to ensure any new company whose score has not yet been computed
    # will temporarily be moved to the last page of search results.
    MAX_DEFAULT_JOB_APP_SCORE = sys.float_info.max

    # Companies have two different SIRET numbers in ASP FluxIAE data ("Vue Structure").
    # The first one is the "SIRET actualisé" which we store as `Company.siret`. It changes rather frequently
    # e.g. each time a Company moves to a new location.
    # The second one is the "SIRET à la signature" which we store as `Company.convention.siret_signature`. By design it
    # almost never changes.
    # Both SIRET numbers are kept up to date by the weekly `import_siae.py` script.
    siret = models.CharField(verbose_name="siret", max_length=14, validators=[validate_siret], db_index=True)
    naf = models.CharField(verbose_name="naf", max_length=5, validators=[validate_naf], blank=True)
    kind = models.CharField(verbose_name="type", max_length=8, choices=CompanyKind.choices, default=CompanyKind.EI)
    # `brand` (or `enseigne` in French) is used to override `name` if needed.
    brand = models.CharField(verbose_name="enseigne", max_length=255, blank=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    email = models.EmailField(verbose_name="e-mail", blank=True)
    # All companies without any existing user require this auth_email
    # for the company secure signup process to be possible.
    # Comes from external exports (ASP, GEIQ...)
    auth_email = models.EmailField(verbose_name="e-mail d'authentification", blank=True)
    website = models.URLField(verbose_name="site web", blank=True)
    description = models.TextField(verbose_name="description", blank=True)
    provided_support = models.TextField(verbose_name="type d'accompagnement", blank=True)

    source = models.CharField(
        verbose_name="source de données", max_length=20, choices=SOURCE_CHOICES, default=SOURCE_ASP
    )

    jobs = models.ManyToManyField("jobs.Appellation", verbose_name="métiers", through="JobDescription", blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="membres",
        through="CompanyMembership",
        through_fields=("company", "user"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        related_name="created_company_set",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )

    # Ability to block new job applications
    block_job_applications = models.BooleanField(verbose_name="blocage des candidatures", default=False)
    job_applications_blocked_at = models.DateTimeField(
        verbose_name="date du dernier blocage de candidatures", blank=True, null=True
    )
    # Spontaneous applications can be opened for a period. A null value indicates spontaneous applications are blocked.
    spontaneous_applications_open_since = models.DateTimeField(
        verbose_name="date d’ouverture des candidatures spontanées",
        blank=True,
        null=True,
        default=timezone.now,
        help_text=(
            "Les candidatures spontanées peuvent être ouvertes pendant 90 jours. Une valeur nulle indique que "
            "les candidatures spontanées sont bloquées."
        ),
    )

    convention = models.ForeignKey(
        "SiaeConvention",
        on_delete=models.RESTRICT,  # A convention should only be deleted if it is no longer linked to any siae.
        blank=True,
        null=True,
        related_name="siaes",
    )

    job_app_score = models.FloatField(
        verbose_name="score de recommandation (ratio de candidatures récentes vs nombre d'offres d'emploi)",
        default=MAX_DEFAULT_JOB_APP_SCORE,
    )
    is_searchable = models.BooleanField(verbose_name="peut apparaître dans la recherche", default=True)

    rdv_solidarites_id = models.IntegerField(
        verbose_name="identifiant d'organisation RDV-Solidarités",
        blank=True,
        null=True,
        unique=True,
        help_text="Permet d'initier la prise de RDV via RDV-Insertion lorsque renseigné.",
        error_messages={"unique": "Une entreprise avec cet ID d'organisation RDV-Solidarités existe déjà."},
    )

    # Use the generic relation to let NotificationSettings being collected on deletion
    notification_settings = GenericRelation(
        "communications.NotificationSettings",
        content_type_field="structure_type",
        object_id_field="structure_pk",
        related_query_name="company",
    )

    fields_history = ArrayField(
        models.JSONField(
            encoder=DjangoJSONEncoder,
        ),
        verbose_name="historique des champs modifiés sur le modèle",
        default=list,
        db_default=[],
    )

    objects = CompanyManager()
    unfiltered_objects = CompanyUnfilteredManager()

    class Meta:
        verbose_name = "entreprise"
        unique_together = ("siret", "kind")
        triggers = [FieldsHistory(name="company_fields_history", fields=["siret"])]

    @property
    def accept_survey_url(self):
        """
        Returns the typeform's satisfaction survey URL to be sent after a successful hiring.
        """
        kwargs = {
            "id_siae": self.pk,
            "type_siae": self.get_kind_display(),
            "region": self.region or "",
            "departement": self.department or "",
        }
        return get_tally_form_url("mY59xq", **kwargs)

    @property
    def display_name(self):
        if self.brand:
            return self.brand
        return self.name.capitalize()

    @property
    def is_active(self):
        if not self.should_have_convention:
            # GEIQ, EA, EATT, OPCS, ... have no convention logic and thus are always active.
            return True
        if self.source == Company.SOURCE_STAFF_CREATED:
            # Staff created companies are always active until eventually
            # converted to ASP source companies by import_siae script.
            # Such commanies are created by our staff when ASP data is lacking
            # the most recent data about them.
            return True
        # ASP source companies and user created companies are active if and only
        # if they have an active convention.
        return self.convention and self.convention.is_active

    @property
    def is_opcs(self):
        return self.kind == CompanyKind.OPCS

    @property
    def is_open_to_spontaneous_applications(self):
        return not self.block_job_applications and self.spontaneous_applications_open_since is not None

    @property
    def obfuscated_auth_email(self):
        """
        Used during the Company secure signup process to avoid
        showing the full auth_email to the new user trying
        to signup, as a pseudo security measure.

        Code from https://gist.github.com/leotada/26d863007e13fb1856cdc047110d0ed6

        emailsecreto@gmail.com => e**********o@gmail.com
        """
        m = self.auth_email.split("@")
        return f"{m[0][0]}{'*' * (len(m[0]) - 2)}{m[0][-1]}@{m[1]}"

    @property
    def siren(self):
        return self.siret[:9]

    @property
    def siret_nic(self):
        """
        The second part of SIRET is called the NIC (numéro interne de classement).
        https://www.insee.fr/fr/metadonnees/definition/c1981
        """
        return self.siret[9:14]

    @property
    def is_subject_to_eligibility_rules(self):
        return self.kind in CompanyKind.siae_kinds()

    @property
    def should_have_convention(self):
        # .values is needed since Python considers the members of CompanyKind to be different
        # instances than SiaeWithConventionKind
        return self.kind in CompanyKind.siae_kinds()

    def get_card_url(self):
        return reverse("companies_views:card", kwargs={"siae_id": self.pk})

    @property
    def signup_magic_link(self):
        return reverse("signup:employer", kwargs={"company_id": self.pk, "token": self.get_token()})

    def get_token(self):
        return company_signup_token_generator.make_token(self)

    def new_signup_activation_email_to_official_contact(self, request):
        """
        Send email to siae.auth_email with a magic link to continue signup.
        """
        if not self.auth_email:
            raise RuntimeError("Siae cannot be signed up for, this should never happen.")
        to = [self.auth_email]
        signup_magic_link = get_absolute_url(self.signup_magic_link)
        context = {"siae": self, "signup_magic_link": signup_magic_link}
        subject = "companies/email/new_signup_activation_email_to_official_contact_subject.txt"
        body = "companies/email/new_signup_activation_email_to_official_contact_body.txt"
        return get_email_message(to, context, subject, body)

    def activate_your_account_email(self):
        if self.has_members or not self.auth_email:
            raise ValidationError("Company cannot be signed up for, this should never happen.")
        to = [self.auth_email]
        context = {"siae": self, "signup_url": get_absolute_url(reverse("signup:company_select"))}
        subject = "companies/email/activate_your_account_subject.txt"
        body = "companies/email/activate_your_account_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def grace_period_end_date(self):
        """
        This method is only called for inactive siaes,
        in other words siaes during or after their grace period,
        to figure out the exact end date of their grace period.
        """
        # This should never happen but let's be defensive in this case.
        if self.is_active:
            return timezone.now() + timezone.timedelta(days=365)

        # This should never happen but let's be defensive in this case.
        if self.source == self.SOURCE_USER_CREATED and not self.convention:
            # A user created siae without convention should not exist, but if it does, it should be considered past
            # its grace period.
            return timezone.now() + timezone.timedelta(days=-1)

        grace_period_start_date = self.convention.deactivated_at
        return grace_period_start_date + timezone.timedelta(days=SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)

    @property
    def grace_period_has_expired(self):
        return not self.is_active and timezone.now() > self.grace_period_end_date

    @property
    def can_have_prior_action(self):
        return self.kind == CompanyKind.GEIQ

    @property
    def can_use_employee_record(self):
        """
        Check if this SIAE can use the employee record app
        """
        return self.kind in self.ASP_EMPLOYEE_RECORD_KINDS and self.convention_id

    @property
    def can_upload_prolongation_report(self):
        """
        Is this SIAE allowed to use / upload a prolongation report file ?
        (temporary: limited to AI only)
        """
        return self.kind == CompanyKind.AI

    @property
    def canonical_company(self):
        """
        Return the canonical company of the current company.
        If the current company has no parent, it is itself its canonical company.
        If the current company has a parent, that parent is the canonical company.
        """
        if self.convention_id and self.source == self.SOURCE_USER_CREATED:
            # Iterate on all() to take advantage of a potential prefetch_related upstream
            # e.g. by populate_metabase_emplois.
            for convention_siae in self.convention.siaes.all():
                if convention_siae.source == self.SOURCE_ASP:
                    return convention_siae
        return self

    @property
    def is_aci_convergence(self):
        return (
            self.kind == CompanyKind.ACI and self.canonical_company.siret in settings.ACI_CONVERGENCE_SIRET_WHITELIST
        )

    def convention_can_be_accessed_by(self, user):
        """
        Decides whether the user can show the siae convention or not.
        In other words, whether the user can access the "My AFs" interface.
        Note that the convention itself does not necessarily exist yet
        e.g. in the case of old user created siaes without convention yet.
        """
        if not self.has_admin(user):
            return False
        if not self.should_have_convention:
            # AF interfaces only makes sense for SIAE, not for GEIQ, EA, etc.
            return False
        if self.source not in [self.SOURCE_ASP, self.SOURCE_USER_CREATED]:
            # AF interfaces do not make sense for staff created siaes, which
            # have no convention yet, and will eventually be converted into
            # siaes of ASP source by `import_siae.py` script.
            return False
        return True

    def convention_can_be_changed_by(self, user):
        """
        Decides whether the user can change the siae convention or not.
        In other words, whether the user can not only access the "My AFs" interface
        but also use it to select a different convention for the siae.
        """
        if not self.convention_can_be_accessed_by(user):
            return False
        # The link between an ASP source siae and its convention
        # is immutable. Only user created siaes can have their
        # convention changed by the user.
        return self.source == self.SOURCE_USER_CREATED

    def get_active_suspension_dates(self):
        active_suspension_dates = (
            self.evaluated_siaes.filter(sanctions__suspension_dates__contains=timezone.localdate())
            .order_by(F("sanctions__suspension_dates__upper").desc(nulls_first=True))
            .values_list("sanctions__suspension_dates", flat=True)[:1]
        )
        return active_suspension_dates[0] if active_suspension_dates else None

    def get_active_suspension_text_with_dates(self):
        active_suspension_dates = self.get_active_suspension_dates()
        if active_suspension_dates is None:
            return ""
        if active_suspension_dates.upper is None:
            return (
                "Dans votre cas, le retrait définitif de la capacité d'auto-prescription est effectif "
                f"depuis le {active_suspension_dates.lower:%d/%m/%Y}."
            )
        return (
            "Dans votre cas, le retrait temporaire de la capacité d'auto-prescription est effectif depuis le "
            f"{active_suspension_dates.lower:%d/%m/%Y} et le sera jusqu'au {active_suspension_dates.upper:%d/%m/%Y}."
        )

    def siret_from_asp_source(self):
        """
        Fetch SIRET number of authoritative SIAE from ASP source
        """
        if self.canonical_company.source == Company.SOURCE_ASP:
            return self.canonical_company.siret
        raise ValidationError("Could not find authoritative SIAE from ASP source")

    def has_job_descriptions_not_updated_recently(self):
        """
        Returns True if the company has at least one job description (or is open to spontaneous applications)
        not updated for at least 60 days.
        """
        DAYS = 60
        if self.is_open_to_spontaneous_applications:
            spontaneous_applications_time_since_last_update = timezone.now() - self.spontaneous_applications_open_since
            if spontaneous_applications_time_since_last_update.days >= DAYS:
                return True

        date_n_days_ago = timezone.now() - timedelta(days=DAYS)
        has_job_descriptions_considered_old = JobDescription.objects.filter(
            is_active=True, company=self, last_employer_update_at__lt=date_n_days_ago
        ).exists()
        return has_job_descriptions_considered_old


class CompanyMembership(MembershipAbstract):
    """Intermediary model between `User` and `Company`."""

    user_kind = UserKind.EMPLOYER

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_companymembership_set",
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        verbose_name="mis à jour par",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "company"], name="user_company_unique"),
        ]


class JobDescriptionQuerySet(models.QuerySet):
    def with_job_applications_count(self, filters=None):
        if filters:
            filters = Q(**filters)

        # For performance reasons, we may decide to replace this join by a sub query one day.
        # This would be a delicate operation as selected_jobs are stored in an intermediary table.
        # Sub queries referencing a unique parent are understandable but when it comes to a "couple",
        # it may be easier to just write raw SQL. But then you lose the ORM benefits.
        # Make sure it's worth the hassle.
        # See `CompanyQuerySet.with_count_recent_received_job_apps`
        return self.annotate(
            job_applications_count=Count(
                "jobapplication",
                filter=filters,
            ),
        )

    def with_annotation_is_unpopular(self):
        # Avoid a circular import
        job_application_model = self.model._meta.get_field("jobapplication").related_model

        job_apps_filters = {
            "jobapplication__created_at__gte": timezone.now()
            - timezone.timedelta(weeks=job_application_model.WEEKS_BEFORE_CONSIDERED_OLD),
        }
        annotation = self.with_job_applications_count(filters=job_apps_filters).annotate(
            is_unpopular=Case(
                When(job_applications_count__lte=self.model.UNPOPULAR_THRESHOLD, then=True),
                default=False,
                output_field=BooleanField(),
            )
        )
        return annotation

    def active(self):
        subquery = Subquery(
            Company.unfiltered_objects.filter(
                pk=OuterRef("company"),
            ).active()
        )
        return self.annotate(is_siae_active=Exists(subquery)).filter(is_active=True, is_siae_active=True)

    def within(self, point, distance_km):
        return self.filter(
            Q(location__isnull=False, location__coords__dwithin=(point, D(km=distance_km)))
            | Q(
                location__isnull=True,
                company__coords__isnull=False,
                company__coords__dwithin=(point, D(km=distance_km)),
            )
        )


class JobDescription(models.Model):
    """
    A job description of a position in an SIAE.
    Intermediary model between `jobs.Appellation` and `Company`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    MAX_UI_RANK = 32767
    UNPOPULAR_THRESHOLD = 1
    # Max number or workable hours per week in France (Code du Travail)
    MAX_WORKED_HOURS_PER_WEEK = 48

    appellation = models.ForeignKey("jobs.Appellation", on_delete=models.RESTRICT)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="job_description_through")
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)
    is_active = models.BooleanField(verbose_name="recrutement ouvert", default=True)
    last_employer_update_at = models.DateTimeField(
        verbose_name="date de dernière mise à jour employeur",
        null=True,
        editable=False,
        db_index=True,
        help_text=(
            "Toute mise à jour d’une fiche de poste à l’état actif effectuée par l’employeur réinitialise cette date."
        ),
    )
    custom_name = models.CharField(verbose_name="nom personnalisé", blank=True, max_length=255)
    description = models.TextField(verbose_name="description", blank=True)
    # is used to order job descriptions in the UI
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    contract_type = models.CharField(
        verbose_name="type de contrat", choices=ContractType.choices, max_length=30, blank=True
    )
    other_contract_type = models.CharField(verbose_name="autre type de contrat", max_length=255, blank=True, null=True)
    location = models.ForeignKey(
        "cities.City",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        verbose_name="localisation du poste",
    )
    hours_per_week = models.PositiveSmallIntegerField(
        verbose_name="nombre d'heures par semaine",
        blank=True,
        null=True,
        validators=[MaxValueValidator(MAX_WORKED_HOURS_PER_WEEK)],
    )
    open_positions = models.PositiveSmallIntegerField(verbose_name="nombre de postes ouverts", blank=True, default=1)
    profile_description = models.TextField(verbose_name="profil recherché et pré-requis", blank=True)
    is_resume_mandatory = models.BooleanField(verbose_name="CV nécessaire pour la candidature", default=False)

    is_qpv_mandatory = models.BooleanField(verbose_name="une clause QPV est nécessaire pour ce poste", default=False)
    market_context_description = models.TextField(verbose_name="contexte du marché", blank=True)

    source_id = models.CharField(verbose_name="ID dans le référentiel source", null=True, blank=True, max_length=255)
    source_kind = models.CharField(
        verbose_name="source de la donnée",
        choices=JobSource.choices,
        max_length=30,
        null=True,
    )
    source_url = models.URLField(verbose_name="URL source de l'offre", max_length=512, null=True, blank=True)
    source_tags = ArrayField(
        base_field=models.CharField(choices=JobSourceTag.choices),
        verbose_name="étiquettes de la source",
        null=True,
    )
    field_history = models.JSONField(
        verbose_name="historique des champs modifiés sur le modèle",
        null=True,
        encoder=DjangoJSONEncoder,
        default=list,
    )

    # Job descriptions are now directly linked to job applications / hirings (`hired_job`).
    # If there's no job description, a new one is automatically created at the end of the hiring process.
    creation_source = models.CharField(
        verbose_name="source de création de la fiche de poste",
        choices=JobDescriptionSource.choices,
        default=JobDescriptionSource.MANUALLY,
    )

    objects = JobDescriptionQuerySet.as_manager()

    class Meta:
        verbose_name = "fiche de poste"
        verbose_name_plural = "fiches de postes"
        ordering = ["appellation__name", "ui_rank"]
        constraints = [
            UniqueConstraint(
                fields=["source_kind", "source_id"],
                condition=Q(source_kind__isnull=False) & Q(source_id__isnull=False) & ~Q(source_id=""),
                name="source_id_kind_unique_without_null_values",
            ),
        ]

    def __str__(self):
        return self.display_name

    def clean(self):
        if self.contract_type == ContractType.OTHER and not self.other_contract_type:
            raise ValidationError(
                {
                    "other_contract_type": "Veuillez préciser le type de contrat.",
                }
            )

    @classmethod
    def from_db(cls, db, field_names, values):
        # this is close to the code we have in itou.users.User.from_db() but we
        # don't want full genericity yet. We could be DRYer by using a mixin later,
        # but we'd need to handle some extra edge cases.
        instance = super().from_db(db, field_names, values)
        setattr(instance, "_old_is_active", instance.is_active)
        return instance

    def save(self, *args, **kwargs):
        if hasattr(self, "_old_is_active") and self._old_is_active != self.is_active:
            self.field_history.append(
                {
                    "field": "is_active",
                    "from": self._old_is_active,
                    "to": self.is_active,
                    "at": timezone.now(),
                }
            )
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("field_history")
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        if self.custom_name:
            return self.custom_name
        return self.appellation.name

    @property
    def display_location(self):
        if self.location:
            return f"{self.location.name} - {self.location.department}"
        return f"{self.company.city} ({self.company.department})"

    @property
    def display_contract_type(self):
        return self.other_contract_type or self.get_contract_type_display

    @property
    def is_external(self):
        return self.source_kind is not None

    @property
    def is_from_pole_emploi(self):
        return self.company.siret == POLE_EMPLOI_SIRET

    @property
    def is_pec_offer(self):
        return self.is_from_pole_emploi and self.source_tags and JobSourceTag.FT_PEC_OFFER.value in self.source_tags

    def get_absolute_url(self):
        if self.is_external:
            return self.source_url
        return get_absolute_url(
            reverse("companies_views:job_description_card", kwargs={"job_description_id": self.pk})
        )


class SiaeConvention(models.Model):
    """
    A SiaeConvention encapsulates the ASP-specific logic to decide whether
    the siaes attached to this SiaeConvention are officially allowed
    to hire within the "Insertion par l'activité économique" system
    and get subventions.

    A SiaeConvention is shared by exactly one siae of ASP source
    and zero or more user created siaes ("Antennes").

    A SiaeConvention has many SiaeFinancialAnnex related objects, and will
    be considered active if and only if at least one SiaeFinancialAnnex is active.

    Note that SiaeConvention is an abstraction of potentially several ASP
    conventions. Ideally a single ASP SIAE has a single ASP convention,
    however in many instances a single ASP SIAE has several active ASP conventions
    at the same time, which we abstract here as a single SiaeConvention object.

    This SiaeConvention abstraction, as there is only one per siae of source ASP,
    is technically equivalent to an siae of ASP source. But we prefer to store
    all those fields in a separate SiaeConvention object instead of storing them
    directly in the Siae model.

    Let's clarify this potentially confusing model on a few examples:

    Example 1)
    One ASP SIAE has one ASP convention with 3 financial annexes.

    Result:
    One Company has one SiaeConvention with 3 SiaeFinancialAnnex instances.

    Example 2)
    One ASP SIAE has 3 ASP conventions each one having 3 financial annexes.

    Result:
    One Company has one SiaeConvention with 3x3=9 SiaeFinancialAnnex instances.

    Example 3)
    One ASP SIAE having 2 "mesures" (EI+AI) has 2 ASP conventions (1 for each "mesure")
    and each ASP Convention has 3 financial annexes.

    Result:
    Two Company instances:
    - one EI Company with one SiaeConvention (EI) having 3 SiaeFinancialAnnex instances.
    - one AI Company with one SiaeConvention (AI) having 3 SiaeFinancialAnnex instances.
    """

    # When a convention is deactivated its siaes still have a partial access
    # to the platform during this grace period.
    DEACTIVATION_GRACE_PERIOD_IN_DAYS = 30

    kind = models.CharField(
        verbose_name="type",
        max_length=4,
        choices=CompanyKind.siae_choices(),
        default=CompanyKind.EI.value,
    )

    # SIAE structures have two different SIRET numbers in ASP FluxIAE data ("Vue Structure").
    # The first one is the "SIRET actualisé" which we store as `siae.siret`. It changes rather frequently
    # e.g. each time a SIAE moves to a new location.
    # The second one is the "SIRET à la signature" which we store as `siae.convention.siret_signature`. By design it
    # almost never changes.
    # Both SIRET numbers are kept up to date by the weekly `import_siae.py` script.
    siret_signature = models.CharField(
        verbose_name="siret à la signature",
        max_length=14,
        validators=[validate_siret],
        db_index=True,
    )

    # Ideally convention.is_active would be a property and not a field.
    # However we have to live with the fact that some of ASP's data is
    # randomly weeks or even months late, as DIRECTTE sometimes take so
    # much time to input the data of their department into the ASP extranet.
    # Thus our staff will regularly need to manually reactivate a convention
    # for weeks or months until we get up-to-date data for it.
    # This is why this field is needed. It is manipulated only by:
    # 1) our staff
    # 2) the `import_siae.py` script
    is_active = models.BooleanField(
        verbose_name="active",
        default=True,
        help_text=(
            "Précise si la convention est active c.a.d. si elle a au moins une annexe financière valide à ce jour."
        ),
        db_index=True,
    )
    # Grace period starts from this date.
    deactivated_at = models.DateTimeField(
        verbose_name="date de désactivation et début de délai de grâce",
        blank=True,
        null=True,
        db_index=True,
    )
    # When itou staff manually reactivates an inactive convention, store who did it and when.
    reactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="réactivée manuellement par",
        related_name="reactivated_siae_convention_set",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # Only staff can update it, and we shouldn't delete one of those accounts
    )
    reactivated_at = models.DateTimeField(verbose_name="date de réactivation manuelle", blank=True, null=True)

    # Internal ID of siaes à la ASP. This ID is supposed to never change,
    # so as long as the ASP keeps including this field in all their exports,
    # it will be easy for us to accurately sync data between exports.
    # Note that this asp_id unicity is based on SIRET only.
    # In other words, if an EI and a ACI share the same SIRET, they also
    # share the same asp_id in ASP's own database.
    # In this example a single siae à la ASP corresponds to two siaes à la Itou.
    asp_id = models.IntegerField(
        verbose_name="ID ASP de la SIAE",
        db_index=True,
    )

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "convention"
        unique_together = (
            ("asp_id", "kind"),
            # Unfortunately the (siret_signature, kind) couple is not unique,
            # as the two asp_ids 2455 and 4281 share the same siret_signature.
            # It is the only exception. Both structures are active.
            # ("siret_signature", "kind"),
        )

    @property
    def siren_signature(self):
        return self.siret_signature[:9]


class SiaeFinancialAnnex(models.Model):
    """
    A SiaeFinancialAnnex allows us to know whether a convention and thus its siaes are active.

    It is often abbreviated as AF ("Annexe Financière") in the codebase.

    A SiaeFinancialAnnex is considered active if and only if it has an active state and an end_date in the future.
    """

    STATE_VALID = "VALIDE"
    STATE_PROVISIONAL = "PROVISOIRE"
    STATE_ARCHIVED = "HISTORISE"
    STATE_CANCELLED = "ANNULE"
    STATE_ENTERED = "SAISI"
    STATE_DRAFT = "BROUILLON"
    STATE_CLOSED = "CLOTURE"
    STATE_REJECTED = "REJETE"

    STATE_CHOICES = (
        (STATE_VALID, "Validée"),
        (STATE_PROVISIONAL, "Provisoire (valide)"),
        (STATE_ARCHIVED, "Archivée (invalide)"),
        (STATE_CANCELLED, "Annulée"),
        (STATE_ENTERED, "Saisie (invalide)"),
        (STATE_DRAFT, "Brouillon (invalide)"),
        (STATE_CLOSED, "Cloturée (invalide)"),
        (STATE_REJECTED, "Rejetée"),
    )

    STATES_ACTIVE = [STATE_VALID, STATE_PROVISIONAL]
    STATES_INACTIVE = [STATE_ARCHIVED, STATE_CANCELLED, STATE_ENTERED, STATE_DRAFT, STATE_CLOSED, STATE_REJECTED]
    STATES_ALL = STATES_ACTIVE + STATES_INACTIVE

    # An AF number is structured as follow (e.g. ACI051170013A0M1):
    # 1) Prefix part:
    # - ACI is the "mesure" (ASP term for "type de structure").
    # - 051 is the department (sometimes two digits and one letter).
    # - 17 are the last 2 digits of the "millésime".
    # - 0013 is the "numéro d'ordre".
    # 2) Suffix part:
    # - A0, A1, A2… is the "numéro d'avenant".
    # - M0, M1, M2… is the "numéro de modification de l'avenant".
    number = models.CharField(
        verbose_name="numéro d'annexe financière",
        max_length=17,
        validators=[validate_af_number],
        unique=True,
        db_index=True,
    )
    state = models.CharField(
        verbose_name="état",
        max_length=20,
        choices=STATE_CHOICES,
    )
    start_at = models.DateField(verbose_name="date de début d'effet")
    end_at = models.DateField(verbose_name="date de fin d'effet")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    convention = models.ForeignKey(
        "SiaeConvention",
        on_delete=models.CASCADE,  # A financial annex cannot exist without a convention
        related_name="financial_annexes",
    )

    class Meta:
        verbose_name = "annexe financière"
        verbose_name_plural = "annexes financières"

    def __str__(self):
        return self.number

    @property
    def number_prefix(self):
        return self.number[:-4]  # all but last 4 characters

    @property
    def number_prefix_with_spaces(self):
        """
        Insert spaces to format the number.
        """
        prefix = self.number_prefix
        return f"{prefix[:-9]} {prefix[-9:-6]} {prefix[-6:-4]} {prefix[-4:]}"

    @property
    def number_suffix(self):
        return self.number[-4:]  # last 4 characters

    @property
    def number_suffix_with_spaces(self):
        """
        Insert spaces to format the number.
        """
        suffix = self.number_suffix
        return f"{suffix[:-2]} {suffix[-2:]}"

    @property
    def number_with_spaces(self):
        """
        Insert spaces to format the number.
        """
        return f"{self.number_prefix_with_spaces} {self.number_suffix_with_spaces}"

    @property
    def is_active(self):
        return self.state in SiaeFinancialAnnex.STATES_ACTIVE and self.end_at > timezone.localdate()
