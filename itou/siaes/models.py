from django.conf import settings
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import BooleanField, Case, Count, Exists, F, OuterRef, Q, Subquery, When
from django.db.models.constraints import UniqueConstraint
from django.db.models.functions import Cast, Coalesce
from django.urls import reverse
from django.utils import timezone

from itou.common_apps.address.models import AddressMixin
from itou.common_apps.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationQuerySet
from itou.siaes.enums import (
    POLE_EMPLOI_SIRET,
    SIAE_WITH_CONVENTION_CHOICES,
    SIAE_WITH_CONVENTION_KINDS,
    CompanyKind,
    ContractNature,
    ContractType,
    JobSource,
)
from itou.utils.emails import get_email_message
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.urls import get_absolute_url, get_tally_form_url
from itou.utils.validators import validate_af_number, validate_naf, validate_siret


class SiaeQuerySet(OrganizationQuerySet):
    @property
    def active_lookup(self):
        # Prefer a sub query to a join for performance reasons.
        # See `self.with_count_recent_received_job_apps`.
        has_active_convention = Exists(SiaeConvention.objects.filter(id=OuterRef("convention_id"), is_active=True))
        return (
            # GEIQ, EA, EATT, ... have no convention logic and thus are always active.
            # `~` means NOT, similarly to dataframes.
            ~Q(kind__in=SIAE_WITH_CONVENTION_KINDS)
            # Staff created siaes are always active until eventually
            # converted to ASP source siaes by import_siae script.
            # Such siaes are created by our staff when ASP data is lacking
            # the most recent data about them.
            | Q(source=Siae.SOURCE_STAFF_CREATED)
            # ASP source siaes and user created siaes are active if and only
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
                WHERE (U0."created_at" >= 2021-06-10 08:45:51.998244 + 00:00 AND U0."to_siae_id" = "siaes_siae"."id")
                GROUP BY U0."to_siae_id"), 0) AS "count_recent_received_job_apps"
        FROM
            "siaes_siae"

        See https://github.com/martsberger/django-sql-utils
        """
        # Avoid a circular import
        job_application_model = self.model._meta.get_field("jobapplication").related_model

        sub_query = Subquery(
            (
                job_application_model.objects.filter(
                    to_siae=OuterRef("id"),
                    created_at__gte=timezone.now()
                    - timezone.timedelta(weeks=job_application_model.WEEKS_BEFORE_CONSIDERED_OLD),
                )
                .values("to_siae")  # group job apps by to_siae
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
                SiaeJobDescription.objects.filter(is_active=True, siae=OuterRef("id"))
                .values("siae")
                .annotate(count=Count("pk"))
                .values("count")
            ),
            output_field=models.IntegerField(),
        )
        return self.annotate(count_active_job_descriptions=Coalesce(sub_query, 0))

    def with_computed_job_app_score(self):
        """
        Employers search results boost SIAE which did not receive enough job applications
        compared to their total job descriptions.
        To do so, the following score is computed:
        ** (total of recent job applications) / (total of active job descriptions) **
        """
        # Transform integer into a float to avoid any weird side effect.
        # See self.with_count_recent_received_job_apps()
        count_recent_received_job_apps = Cast("count_recent_received_job_apps", output_field=models.FloatField())

        # Check if a job description exists before computing the score.
        has_active_job_desc = Exists(SiaeJobDescription.objects.filter(siae=OuterRef("pk"), is_active=True))

        # Transform integer into a float to avoid any weird side effect.
        # See self.with_count_active_job_descriptions
        count_active_job_descriptions = Cast("count_active_job_descriptions", output_field=models.FloatField())

        # Score computing.
        get_score = Cast(
            count_recent_received_job_apps / count_active_job_descriptions, output_field=models.FloatField()
        )

        return (
            self.with_count_recent_received_job_apps()
            .with_count_active_job_descriptions()
            .annotate(
                computed_job_app_score=Case(
                    When(has_active_job_desc, then=get_score),
                    default=None,
                )
            )
        )

    def with_has_active_members(self):
        # Prefer a sub query to a join for performance reasons.
        # See `self.with_count_recent_received_job_apps`.
        return self.annotate(
            has_active_members=Exists(SiaeMembership.objects.filter(siae=OuterRef("pk"), is_active=True))
        )


class SiaeManager(models.Manager.from_queryset(SiaeQuerySet)):
    def get_queryset(self):
        return super().get_queryset().exclude(siret=POLE_EMPLOI_SIRET)


class Siae(AddressMixin, OrganizationAbstract):
    """
    Structures d'insertion par l'activité économique.

    To retrieve jobs of an siae:
        self.jobs.all()             <QuerySet [<Appellation>, ...]>
        self.job_description_through.all()     <QuerySet [<SiaeJobDescription>, ...]>
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

    # These kinds of SIAE can use employee record app to send data to ASP
    ASP_EMPLOYEE_RECORD_KINDS = [CompanyKind.EI, CompanyKind.ACI, CompanyKind.AI, CompanyKind.ETTI]

    # SIAE structures have two different SIRET numbers in ASP FluxIAE data ("Vue Structure").
    # The first one is the "SIRET actualisé" which we store as `siae.siret`. It changes rather frequently
    # e.g. each time a SIAE moves to a new location.
    # The second one is the "SIRET à la signature" which we store as `siae.convention.siret_signature`. By design it
    # almost never changes.
    # Both SIRET numbers are kept up to date by the weekly `import_siae.py` script.
    siret = models.CharField(verbose_name="siret", max_length=14, validators=[validate_siret], db_index=True)
    naf = models.CharField(verbose_name="naf", max_length=5, validators=[validate_naf], blank=True)
    kind = models.CharField(verbose_name="type", max_length=8, choices=CompanyKind.choices, default=CompanyKind.EI)
    # `brand` (or `enseigne` in French) is used to override `name` if needed.
    brand = models.CharField(verbose_name="enseigne", max_length=255, blank=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    email = models.EmailField(verbose_name="e-mail", blank=True)
    # All siaes without any existing user require this auth_email
    # for the siae secure signup process to be possible.
    # Comes from external exports (ASP, GEIQ...)
    auth_email = models.EmailField(verbose_name="e-mail d'authentification", blank=True)
    website = models.URLField(verbose_name="site web", blank=True)
    description = models.TextField(verbose_name="description", blank=True)
    provided_support = models.TextField(verbose_name="type d'accompagnement", blank=True)

    source = models.CharField(
        verbose_name="source de données", max_length=20, choices=SOURCE_CHOICES, default=SOURCE_ASP
    )

    jobs = models.ManyToManyField("jobs.Appellation", verbose_name="métiers", through="SiaeJobDescription", blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="membres",
        through="SiaeMembership",
        through_fields=("siae", "user"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        related_name="created_siae_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Ability to block new job applications
    block_job_applications = models.BooleanField(verbose_name="blocage des candidatures", default=False)
    job_applications_blocked_at = models.DateTimeField(
        verbose_name="date du dernier blocage de candidatures", blank=True, null=True
    )

    # A convention can only be deleted if it is no longer linked to any siae.
    convention = models.ForeignKey(
        "SiaeConvention",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
        related_name="siaes",
    )

    job_app_score = models.FloatField(
        verbose_name="score de recommandation (ratio de candidatures récentes vs nombre d'offres d'emploi)", null=True
    )

    objects = SiaeManager()
    unfiltered_objects = SiaeQuerySet.as_manager()

    class Meta:
        verbose_name = "entreprise"
        unique_together = ("siret", "kind")

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
        if self.source == Siae.SOURCE_STAFF_CREATED:
            # Staff created siaes are always active until eventually
            # converted to ASP source siaes by import_siae script.
            # Such siaes are created by our staff when ASP data is lacking
            # the most recent data about them.
            return True
        # ASP source siaes and user created siaes are active if and only
        # if they have an active convention.
        return self.convention and self.convention.is_active

    @property
    def asp_id(self):
        if self.convention:
            return self.convention.asp_id
        return None

    @property
    def is_opcs(self):
        return self.kind == CompanyKind.OPCS

    @property
    def obfuscated_auth_email(self):
        """
        Used during the SIAE secure signup process to avoid
        showing the full auth_email to the new user trying
        to signup, as a pseudo security measure.

        Code from https://gist.github.com/leotada/26d863007e13fb1856cdc047110d0ed6

        emailsecreto@gmail.com => e**********o@gmail.com
        """
        m = self.auth_email.split("@")
        return f'{m[0][0]}{"*"*(len(m[0])-2)}{m[0][-1]}@{m[1]}'

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
        return self.kind in SIAE_WITH_CONVENTION_KINDS

    @property
    def should_have_convention(self):
        # .values is needed since Python considers the members of CompanyKind to be different
        # instances than SiaeWithConventionKind
        return self.kind in SIAE_WITH_CONVENTION_KINDS

    def get_card_url(self):
        return reverse("companies_views:card", kwargs={"siae_id": self.pk})

    @property
    def signup_magic_link(self):
        return reverse("signup:siae_user", kwargs={"siae_id": self.pk, "token": self.get_token()})

    def get_token(self):
        return siae_signup_token_generator.make_token(self)

    def new_signup_activation_email_to_official_contact(self, request):
        """
        Send email to siae.auth_email with a magic link to continue signup.
        """
        if not self.auth_email:
            raise RuntimeError("Siae cannot be signed up for, this should never happen.")
        to = [self.auth_email]
        signup_magic_link = get_absolute_url(self.signup_magic_link)
        context = {"siae": self, "signup_magic_link": signup_magic_link}
        subject = "siaes/email/new_signup_activation_email_to_official_contact_subject.txt"
        body = "siaes/email/new_signup_activation_email_to_official_contact_body.txt"
        return get_email_message(to, context, subject, body)

    def activate_your_account_email(self):
        if self.has_members or not self.auth_email:
            raise ValidationError("Siae cannot be signed up for, this should never happen.")
        to = [self.auth_email]
        context = {"siae": self, "signup_url": reverse("signup:siae_select")}
        subject = "siaes/email/activate_your_account_subject.txt"
        body = "siaes/email/activate_your_account_body.txt"
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
        # No need to check if convention is active (done by middleware)
        return self.kind in self.ASP_EMPLOYEE_RECORD_KINDS

    @property
    def can_upload_prolongation_report(self):
        """
        Is this SIAE allowed to use / upload a prolongation report file ?
        (temporary: limited to AI only)
        """
        return self.kind == CompanyKind.AI

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


class SiaeMembership(MembershipAbstract):
    """Intermediary model between `User` and `Siae`."""

    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_siaemembership_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="mis à jour par",
    )
    notifications = models.JSONField(verbose_name="notifications", default=dict, blank=True)

    class Meta:
        unique_together = ("user_id", "siae_id")


class SiaeJobDescriptionQuerySet(models.QuerySet):
    def with_job_applications_count(self, filters=None):
        if filters:
            filters = Q(**filters)

        # For performance reasons, we may decide to replace this join by a sub query one day.
        # This would be a delicate operation as selected_jobs are stored in an intermediary table.
        # Sub queries referencing a unique parent are understandable but when it comes to a "couple",
        # it may be easier to just write raw SQL. But then you lose the ORM benefits.
        # Make sure it's worth the hassle.
        # See `SiaeQuerySet.with_count_recent_received_job_apps`
        return self.annotate(
            job_applications_count=Count(
                "jobapplication",
                filter=filters,
            ),
        )

    def with_annotation_is_popular(self):
        # Avoid a circular import
        from itou.job_applications.models import JobApplicationWorkflow

        job_apps_filters = {"jobapplication__state__in": JobApplicationWorkflow.PENDING_STATES}
        annotation = self.with_job_applications_count(filters=job_apps_filters).annotate(
            is_popular=Case(
                When(job_applications_count__gt=self.model.POPULAR_THRESHOLD, then=True),
                default=False,
                output_field=BooleanField(),
            )
        )
        return annotation

    def order_by_most_recent(self):
        return self.order_by("-updated_at", "-created_at")

    def active(self):
        subquery = Subquery(
            Siae.unfiltered_objects.filter(
                pk=OuterRef("siae"),
            ).active()
        )
        return self.annotate(is_siae_active=Exists(subquery)).filter(is_active=True, is_siae_active=True)

    def within(self, point, distance_km):
        return self.filter(
            Q(location__isnull=False, location__coords__dwithin=(point, D(km=distance_km)))
            | Q(
                location__isnull=True,
                siae__coords__isnull=False,
                siae__coords__dwithin=(point, D(km=distance_km)),
            )
        )


class SiaeJobDescription(models.Model):
    """
    A job description of a position in an SIAE.
    Intermediary model between `jobs.Appellation` and `Siae`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    MAX_UI_RANK = 32767
    POPULAR_THRESHOLD = 20
    # Max number or workable hours per week in France (Code du Travail)
    MAX_WORKED_HOURS_PER_WEEK = 48

    appellation = models.ForeignKey("jobs.Appellation", on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE, related_name="job_description_through")
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)
    is_active = models.BooleanField(verbose_name="recrutement ouvert", default=True)
    custom_name = models.CharField(verbose_name="nom personnalisé", blank=True, max_length=255)
    description = models.TextField(verbose_name="description", blank=True)
    # is used to order job descriptions in the UI
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    contract_type = models.CharField(
        verbose_name="type de contrat", choices=ContractType.choices, max_length=30, blank=True
    )
    other_contract_type = models.CharField(verbose_name="autre type de contrat", max_length=255, blank=True, null=True)
    contract_nature = models.CharField(
        verbose_name="nature du contrat", choices=ContractNature.choices, max_length=64, blank=True, null=True
    )
    location = models.ForeignKey(
        "cities.City",
        on_delete=models.SET_NULL,
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
    field_history = models.JSONField(
        verbose_name="historique des champs modifiés sur le modèle",
        null=True,
        encoder=DjangoJSONEncoder,
        default=list,
    )

    objects = SiaeJobDescriptionQuerySet.as_manager()

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
            return f"{self.location.name} ({self.location.department})"
        return f"{self.siae.city} ({self.siae.department})"

    @property
    def display_contract_type(self):
        return self.other_contract_type or self.get_contract_type_display

    @property
    def is_external(self):
        return self.source_kind is not None

    @property
    def is_from_pole_emploi(self):
        return self.siae.siret == POLE_EMPLOI_SIRET

    @property
    def is_pec_offer(self):
        return self.is_from_pole_emploi and self.contract_nature == ContractNature.PEC_OFFER

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
    One Siae has one SiaeConvention with 3 SiaeFinancialAnnex instances.

    Example 2)
    One ASP SIAE has 3 ASP conventions each one having 3 financial annexes.

    Result:
    One Siae has one SiaeConvention with 3x3=9 SiaeFinancialAnnex instances.

    Example 3)
    One ASP SIAE having 2 "mesures" (EI+AI) has 2 ASP conventions (1 for each "mesure")
    and each ASP Convention has 3 financial annexes.

    Result:
    Two Siae instances:
    - one EI Siae with one SiaeConvention (EI) having 3 SiaeFinancialAnnex instances.
    - one AI Siae with one SiaeConvention (AI) having 3 SiaeFinancialAnnex instances.
    """

    # When a convention is deactivated its siaes still have a partial access
    # to the platform during this grace period.
    DEACTIVATION_GRACE_PERIOD_IN_DAYS = 30

    kind = models.CharField(
        verbose_name="type",
        max_length=4,
        choices=SIAE_WITH_CONVENTION_CHOICES,
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
        verbose_name="date de  désactivation et début de délai de grâce",
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
        on_delete=models.SET_NULL,
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

    A SiaeFinancialAnnex is considered active if and only if it has an active stats and an end_date in the future.
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
    start_at = models.DateTimeField(verbose_name="date de début d'effet")
    end_at = models.DateTimeField(verbose_name="date de fin d'effet")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    # A financial annex cannot exist without a convention, and
    # deleting a convention will delete all its financial annexes.
    convention = models.ForeignKey(
        "SiaeConvention",
        on_delete=models.CASCADE,
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
        return self.state in SiaeFinancialAnnex.STATES_ACTIVE and self.end_at > timezone.now()
