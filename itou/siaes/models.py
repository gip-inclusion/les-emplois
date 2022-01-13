from django.conf import settings
from django.contrib.gis.measure import D
from django.db import models
from django.db.models import BooleanField, Case, Count, Exists, OuterRef, Prefetch, Q, Subquery, When
from django.db.models.functions import Cast, Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlencode, urlsafe_base64_encode

from itou.common_apps.address.models import AddressMixin
from itou.common_apps.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationQuerySet
from itou.utils.emails import get_email_message
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_af_number, validate_naf, validate_siret


class SiaeQuerySet(OrganizationQuerySet):
    @property
    def active_lookup(self):
        # Prefer a sub query to a join for performance reasons.
        # See `self.with_count_recent_received_job_apps`.
        has_active_convention = Exists(SiaeConvention.objects.filter(id=OuterRef("convention_id"), is_active=True))
        return (
            # GEIQ, EA, EATT, ACIPHC... have no convention logic and thus are always active.
            # `~` means NOT, similarly to dataframes.
            ~Q(kind__in=Siae.ASP_MANAGED_KINDS)
            # Staff created siaes are always active until eventually
            # converted to ASP source siaes by import_siae script.
            # Such siaes are created by our staff when ASP data is lacking
            # the most recent data about them.
            | Q(source=Siae.SOURCE_STAFF_CREATED)
            # ASP source siaes and user created siaes are active if and only
            # if they have an active convention.
            | has_active_convention
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

    def prefetch_job_description_through(self, **kwargs):
        qs = (
            SiaeJobDescription.objects.filter(**kwargs)
            .with_annotation_is_popular()
            .select_related("appellation__rome")
            .order_by("-updated_at", "-created_at")
        )
        return self.prefetch_related(Prefetch("job_description_through", queryset=qs))

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

    def with_job_app_score(self):
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
                job_app_score=Case(
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


class Siae(AddressMixin, OrganizationAbstract):
    """
    Structures d'insertion par l'activité économique.

    To retrieve jobs of an siae:
        self.jobs.all()             <QuerySet [<Appellation>, ...]>
        self.job_description_through.all()     <QuerySet [<SiaeJobDescription>, ...]>
    """

    KIND_EI = "EI"
    KIND_AI = "AI"
    KIND_ACI = "ACI"

    # When an ACI does PHC ("Premières Heures en Chantier"), we have both an ACI created by
    # the SIAE ASP import (plus its ACI antenna) and an ACIPHC created by our staff (plus its ACIPHC antenna).
    # The first one is managed by ASP data, the second one is managed by our staff.
    KIND_ACIPHC = "ACIPHC"

    KIND_ETTI = "ETTI"
    KIND_EITI = "EITI"
    KIND_GEIQ = "GEIQ"
    KIND_EA = "EA"
    KIND_EATT = "EATT"

    KIND_CHOICES = (
        (KIND_EI, "Entreprise d'insertion"),  # Regroupées au sein de la fédération des entreprises d'insertion.
        (KIND_AI, "Association intermédiaire"),
        (KIND_ACI, "Atelier chantier d'insertion"),
        (KIND_ACIPHC, "Atelier chantier d'insertion premières heures en chantier"),
        (KIND_ETTI, "Entreprise de travail temporaire d'insertion"),
        (KIND_EITI, "Entreprise d'insertion par le travail indépendant"),
        (KIND_GEIQ, "Groupement d'employeurs pour l'insertion et la qualification"),
        (KIND_EA, "Entreprise adaptée"),
        (KIND_EATT, "Entreprise adaptée de travail temporaire"),
    )

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

    # ASP data is used to keep the siae data of these kinds in sync.
    # These kinds and only these kinds thus have convention/AF logic.
    ASP_MANAGED_KINDS = [KIND_EI, KIND_AI, KIND_ACI, KIND_ETTI, KIND_EITI]

    # These kinds of SIAE can use employee record app to send data to ASP
    ASP_EMPLOYEE_RECORD_KINDS = [KIND_EI, KIND_ACI, KIND_AI, KIND_ETTI]

    # https://code.travail.gouv.fr/code-du-travail/l5132-4
    # https://www.legifrance.gouv.fr/eli/loi/2018/9/5/2018-771/jo/article_83
    ELIGIBILITY_REQUIRED_KINDS = ASP_MANAGED_KINDS + [KIND_ACIPHC]

    # SIAE structures have two different SIRET numbers in ASP FluxIAE data ("Vue Structure").
    # The first one is the "SIRET actualisé" which we store as `siae.siret`. It changes rather frequently
    # e.g. each time a SIAE moves to a new location.
    # The second one is the "SIRET à la signature" which we store as `siae.convention.siret_signature`. By design it
    # almost never changes.
    # Both SIRET numbers are kept up to date by the weekly `import_siae.py` script.
    siret = models.CharField(verbose_name="Siret", max_length=14, validators=[validate_siret], db_index=True)
    naf = models.CharField(verbose_name="Naf", max_length=5, validators=[validate_naf], blank=True)
    kind = models.CharField(verbose_name="Type", max_length=6, choices=KIND_CHOICES, default=KIND_EI)
    # `brand` (or `enseigne` in French) is used to override `name` if needed.
    brand = models.CharField(verbose_name="Enseigne", max_length=255, blank=True)
    phone = models.CharField(verbose_name="Téléphone", max_length=20, blank=True)
    email = models.EmailField(verbose_name="E-mail", blank=True)
    # All siaes without any existing user require this auth_email
    # for the siae secure signup process to be possible.
    # Comes from external exports (ASP, GEIQ...)
    auth_email = models.EmailField(verbose_name="E-mail d'authentification", blank=True)
    website = models.URLField(verbose_name="Site web", blank=True)
    description = models.TextField(verbose_name="Description", blank=True)

    source = models.CharField(
        verbose_name="Source de données", max_length=20, choices=SOURCE_CHOICES, default=SOURCE_ASP
    )

    jobs = models.ManyToManyField("jobs.Appellation", verbose_name="Métiers", through="SiaeJobDescription", blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="Membres",
        through="SiaeMembership",
        through_fields=("siae", "user"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Créé par",
        related_name="created_siae_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Ability to block new job applications
    block_job_applications = models.BooleanField(verbose_name="Blocage des candidatures", default=False)
    job_applications_blocked_at = models.DateTimeField(
        verbose_name="Date du dernier blocage de candidatures", blank=True, null=True
    )

    # A convention can only be deleted if it is no longer linked to any siae.
    convention = models.ForeignKey(
        "SiaeConvention",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
        related_name="siaes",
    )

    objects = models.Manager.from_queryset(SiaeQuerySet)()

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprises"
        unique_together = ("siret", "kind")

    @property
    def accept_survey_url(self):
        """
        Returns the typeform's satisfaction survey URL to be sent after a successful hiring.
        """
        args = {
            "id_siae": self.pk,
            "region": self.region or "",
            "type_siae": self.get_kind_display(),
            "departement": self.department or "",
        }
        qs = urlencode(args)
        return f"{settings.TYPEFORM_URL}/to/nUjfDnrA?{qs}"

    @property
    def display_name(self):
        if self.brand:
            return self.brand
        return self.name.capitalize()

    @property
    def is_active(self):
        if not self.is_asp_managed:
            # GEIQ, EA, EATT, ACIPHC... have no convention logic and thus are always active.
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
        return self.kind in self.ELIGIBILITY_REQUIRED_KINDS

    @property
    def is_asp_managed(self):
        return self.kind in self.ASP_MANAGED_KINDS

    def get_card_url(self):
        return reverse("siaes_views:card", kwargs={"siae_id": self.pk})

    @property
    def signup_magic_link(self):
        return reverse(
            "signup:siae", kwargs={"encoded_siae_id": self.get_encoded_siae_id(), "token": self.get_token()}
        )

    def get_encoded_siae_id(self):
        return urlsafe_base64_encode(force_bytes(self.pk))

    def get_token(self):
        return siae_signup_token_generator.make_token(self)

    def new_signup_activation_email_to_official_contact(self, request):
        """
        Send email to siae.auth_email with a magic link to continue signup.

        Request object is needed to build absolute URL for magic link in email body.
        See https://stackoverflow.com/questions/2345708/how-can-i-get-the-full-absolute-url-with-domain-in-django
        """
        if not self.auth_email:
            raise RuntimeError("Siae cannot be signed up for, this should never happen.")
        to = [self.auth_email]
        signup_magic_link = request.build_absolute_uri(self.signup_magic_link)
        context = {"siae": self, "signup_magic_link": signup_magic_link}
        subject = "siaes/email/new_signup_activation_email_to_official_contact_subject.txt"
        body = "siaes/email/new_signup_activation_email_to_official_contact_body.txt"
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
    def can_use_employee_record(self):
        """
        Check if this SIAE can use the employee record app
        """
        # No need to check if convention is active (done by middleware)
        return self.kind in self.ASP_EMPLOYEE_RECORD_KINDS

    def convention_can_be_accessed_by(self, user):
        """
        Decides whether the user can show the siae convention or not.
        In other words, whether the user can access the "My AFs" interface.
        Note that the convention itself does not necessarily exist yet
        e.g. in the case of old user created siaes without convention yet.
        """
        if not self.has_admin(user):
            return False
        if not self.is_asp_managed:
            # AF interfaces only makes sense for SIAE, not for GEIQ EA ACIPHC etc.
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


class SiaeMembership(MembershipAbstract):
    """Intermediary model between `User` and `Siae`."""

    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_siaemembership_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )
    notifications = models.JSONField(verbose_name=("Notifications"), default=dict, blank=True)

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
        from itou.job_applications.models import JobApplicationWorkflow  # pylint: disable=import-outside-toplevel

        job_apps_filters = {"jobapplication__state__in": JobApplicationWorkflow.PENDING_STATES}
        annotation = self.with_job_applications_count(filters=job_apps_filters).annotate(
            is_popular=Case(
                When(job_applications_count__gt=self.model.POPULAR_THRESHOLD, then=True),
                default=False,
                output_field=BooleanField(),
            )
        )
        return annotation


class SiaeJobDescription(models.Model):
    """
    A job description of a position in an SIAE.
    Intermediary model between `jobs.Appellation` and `Siae`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    MAX_UI_RANK = 32767
    POPULAR_THRESHOLD = 20

    appellation = models.ForeignKey("jobs.Appellation", on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE, related_name="job_description_through")
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True, db_index=True)
    is_active = models.BooleanField(verbose_name="Recrutement ouvert", default=True)
    custom_name = models.CharField(verbose_name="Nom personnalisé", blank=True, max_length=255)
    description = models.TextField(verbose_name="Description", blank=True)
    # TODO: this will be used to order job description in UI.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)

    objects = models.Manager.from_queryset(SiaeJobDescriptionQuerySet)()

    class Meta:
        verbose_name = "Fiche de poste"
        verbose_name_plural = "Fiches de postes"
        unique_together = ("appellation", "siae")
        ordering = ["appellation__name", "ui_rank"]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def display_name(self):
        if self.custom_name:
            return self.custom_name
        return self.appellation.name

    def get_absolute_url(self):
        return reverse("siaes_views:job_description_card", kwargs={"job_description_id": self.pk})


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

    KIND_EI = "EI"
    KIND_AI = "AI"
    KIND_ACI = "ACI"
    KIND_ETTI = "ETTI"
    KIND_EITI = "EITI"

    KIND_CHOICES = (
        (KIND_EI, "Entreprise d'insertion"),
        (KIND_AI, "Association intermédiaire"),
        (KIND_ACI, "Atelier chantier d'insertion"),
        (KIND_ETTI, "Entreprise de travail temporaire d'insertion"),
        (KIND_EITI, "Entreprise d'insertion par le travail indépendant"),
    )

    kind = models.CharField(verbose_name="Type", max_length=4, choices=KIND_CHOICES, default=KIND_EI)

    # SIAE structures have two different SIRET numbers in ASP FluxIAE data ("Vue Structure").
    # The first one is the "SIRET actualisé" which we store as `siae.siret`. It changes rather frequently
    # e.g. each time a SIAE moves to a new location.
    # The second one is the "SIRET à la signature" which we store as `siae.convention.siret_signature`. By design it
    # almost never changes.
    # Both SIRET numbers are kept up to date by the weekly `import_siae.py` script.
    siret_signature = models.CharField(
        verbose_name="Siret à la signature",
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
        verbose_name="Active",
        default=True,
        help_text=(
            "Précise si la convention est active c.a.d. si elle a au moins une annexe financière valide à ce jour."
        ),
        db_index=True,
    )
    # Grace period starts from this date.
    deactivated_at = models.DateTimeField(
        verbose_name="Date de  désactivation et début de délai de grâce",
        blank=True,
        null=True,
        db_index=True,
    )
    # When itou staff manually reactivates an inactive convention, store who did it and when.
    reactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Réactivée manuellement par",
        related_name="reactivated_siae_convention_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reactivated_at = models.DateTimeField(verbose_name="Date de réactivation manuelle", blank=True, null=True)

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

    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True)

    class Meta:
        verbose_name = "Convention"
        verbose_name_plural = "Conventions"
        unique_together = (
            ("asp_id", "kind"),
            # Unfortunately the (siret_signature, kind) couple is not unique,
            # as the two asp_ids 2455 and 4281 share the same siret_signature.
            # It is the only exception. Both structures are active.
            # ("siret_signature", "kind"),
        )

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

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
        verbose_name="Numéro d'annexe financière",
        max_length=17,
        validators=[validate_af_number],
        unique=True,
        db_index=True,
    )
    state = models.CharField(
        verbose_name="Etat",
        max_length=20,
        choices=STATE_CHOICES,
    )
    start_at = models.DateTimeField(verbose_name="Date de début d'effet")
    end_at = models.DateTimeField(verbose_name="Date de fin d'effet")

    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True)

    # A financial annex cannot exist without a convention, and
    # deleting a convention will delete all its financial annexes.
    convention = models.ForeignKey(
        "SiaeConvention",
        on_delete=models.CASCADE,
        related_name="financial_annexes",
    )

    class Meta:
        verbose_name = "Annexe financière"
        verbose_name_plural = "Annexes financières"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

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
