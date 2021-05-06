import datetime
import random

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import models
from django.db.models import BooleanField, Case, Count, F, Prefetch, Q, When
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from itou.utils.address.models import AddressMixin
from itou.utils.emails import get_email_message
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_af_number, validate_naf, validate_siret


class SiaeQuerySet(models.QuerySet):
    @property
    def active_lookup(self):
        return (
            # GEIQ, EA, ACIPHC... have no convention logic and thus are always active.
            # `~` means NOT, similarly to dataframes.
            ~Q(kind__in=Siae.ASP_MANAGED_KINDS)
            # Staff created siaes are always active until eventually
            # converted to ASP source siaes by import_siae script.
            # Such siaes are created by our staff when ASP data is lacking
            # the most recent data about them.
            | Q(source=Siae.SOURCE_STAFF_CREATED)
            # ASP source siaes and user created siaes are active if and only
            # if they have an active convention.
            | Q(convention__is_active=True)
        )

    def active(self):
        return self.select_related("convention").filter(self.active_lookup)

    def active_or_in_grace_period(self):
        now = timezone.now()
        grace_period = timezone.timedelta(days=SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)
        return self.select_related("convention").filter(
            self.active_lookup
            # All user created siaes should have a convention but a small
            # number of them (79 as of April 2021) don't because they
            # were created before convention assignment was automated.
            # This number will only decrease over time as siae admin users
            # select their convention.
            # We consider them as experiencing their grace period.
            | Q(source=Siae.SOURCE_USER_CREATED, convention__isnull=True)
            # Include siaes experiencing their grace period.
            | Q(convention__deactivated_at__gte=now - grace_period)
        )

    def within(self, point, distance_km):
        return (
            self.filter(coords__distance_lte=(point, D(km=distance_km)))
            .annotate(distance=Distance("coords", point))
            .order_by("distance")
        )

    def prefetch_job_description_through(self, **kwargs):
        qs = (
            SiaeJobDescription.objects.filter(**kwargs)
            .with_annotation_is_popular()
            .select_related("appellation__rome")
        )
        return self.prefetch_related(Prefetch("job_description_through", queryset=qs))

    def member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(members=user, members__is_active=True)

    def add_shuffled_rank(self):
        """
        Add a shuffled rank using a determistic seed which changes every day,
        which can then later be used to shuffle results.

        We may later implement a more rigorous shuffling but this will
        require setting up a daily cronjob to rebuild the shuffling index
        with new random values.

        Note that we have about 3K siaes.

        We produce a large pseudo-random integer on the fly from `id`
        with the static PG expression `(A+id)*(B+id)`.

        It is important that this large integer is far from zero to avoid
        that id=1,2,3 always stay on the top of the list.
        Thus we choose rather large A and B.

        We then take a modulo which changes everyday.
        """
        # Seed changes every day at midnight.
        random.seed(datetime.date.today())
        # a*b should always be larger than the largest possible value of c,
        # so that id=1,2,3 do not always stay on top of the list.
        # ( 1K * 1K = 1M > 10K )
        a = random.randint(1000, 10000)
        b = random.randint(1000, 10000)
        # As we generally have about 100 results to shuffle, we choose c larger
        # than this so as to avoid collisions as much as possible.
        c = random.randint(1000, 10000)
        shuffle_expression = (a + F("id")) * (b + F("id")) % c
        return self.annotate(shuffled_rank=shuffle_expression)


class Siae(AddressMixin):  # Do not forget the mixin!
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

    siret = models.CharField(verbose_name="Siret", max_length=14, validators=[validate_siret], db_index=True)

    # https://code.travail.gouv.fr/code-du-travail/l5132-4
    # https://www.legifrance.gouv.fr/eli/loi/2018/9/5/2018-771/jo/article_83
    ELIGIBILITY_REQUIRED_KINDS = ASP_MANAGED_KINDS + [KIND_ACIPHC]

    naf = models.CharField(verbose_name="Naf", max_length=5, validators=[validate_naf], blank=True)
    kind = models.CharField(verbose_name="Type", max_length=6, choices=KIND_CHOICES, default=KIND_EI)
    name = models.CharField(verbose_name="Nom", max_length=255)
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
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True)

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
        verbose_name = "Structure d'insertion par l'activité économique"
        verbose_name_plural = "Structures d'insertion par l'activité économique"
        unique_together = ("siret", "kind")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add `kind` attributes, e.g.: `self.is_kind_etti`.
        for kind, _description in self.KIND_CHOICES:
            setattr(self, f"is_kind_{kind.lower()}", kind == self.kind)

    def __str__(self):
        return f"{self.siret} {self.display_name}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def display_name(self):
        if self.brand:
            return self.brand
        return self.name.capitalize()

    @property
    def is_active(self):
        if not self.is_asp_managed:
            # GEIQ, EA, ACIPHC... have no convention logic and thus are always active.
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
    def has_members(self):
        return self.active_members.exists()

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

    def has_member(self, user):
        return self.active_members.filter(pk=user.pk).exists()

    def has_admin(self, user):
        return self.active_admin_members.filter(pk=user.pk).exists()

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
    def active_members(self):
        """
        In this context, active == has an active membership AND user is still active
        """
        return self.members.filter(is_active=True, siaemembership__is_active=True)

    @property
    def deactivated_members(self):
        """
        List of previous members of the structure, still active as user (from the model POV)
        but deactivated by an admin at some point in time.
        """
        return self.members.filter(is_active=True, siaemembership__is_active=False)

    @property
    def active_admin_members(self):
        """
        Active admin members:
        active user/admin in this context means both:
        * user.is_active: user is able to do something on the platform
        * user.membership.is_active: is a member of this structure

        The `self` reference is mandatory even if confusing (many SIAE memberships possible for a given member).
        Will be optimized later with Qs.
        """
        return self.members.filter(is_active=True, siaemembership__is_active=True, siaemembership__is_siae_admin=True)

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

    def member_deactivation_email(self, user):
        """
        Send email when an admin of the structure disables the membership of a given user (deactivation).
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/member_deactivation_email_subject.txt"
        body = "common/emails/member_deactivation_email_body.txt"
        return get_email_message(to, context, subject, body)

    def member_activation_email(self, user):
        """
        Send email when an admin of the structure reactivates the membership of a given user.
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/member_activation_email_subject.txt"
        body = "common/emails/member_activation_email_body.txt"
        return get_email_message(to, context, subject, body)

    def add_admin_email(self, user):
        """
        Send info email to a new admin of the SIAE (added)
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/add_admin_email_subject.txt"
        body = "common/emails/add_admin_email_body.txt"
        return get_email_message(to, context, subject, body)

    def remove_admin_email(self, user):
        """
        Send info email to a former admin of the SIAE (removed)
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/remove_admin_email_subject.txt"
        body = "common/emails/remove_admin_email_body.txt"
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

        if self.source == self.SOURCE_USER_CREATED and not self.convention:
            # All user created siaes should have a convention but a small
            # number of them (79 as of April 2021) don't because they
            # were created before convention assignment was automated.
            # This number will only decrease over time as siae admin users
            # select their convention.
            # We consider them as experiencing their grace period.
            return timezone.now() + timezone.timedelta(days=SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)

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


class SiaeMembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, user__is_active=True)


class SiaeMembership(models.Model):
    """Intermediary model between `User` and `Siae`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name="Date d'adhésion", default=timezone.now)
    is_siae_admin = models.BooleanField(verbose_name="Administrateur de la SIAE", default=False)
    is_active = models.BooleanField("Rattachement actif", default=True)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", null=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_siaemembership_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )
    notifications = models.JSONField(verbose_name=("Notifications"), default=dict, blank=True)

    objects = models.Manager.from_queryset(SiaeMembershipQuerySet)()

    class Meta:
        unique_together = ("user_id", "siae_id")

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def deactivate_membership_by_user(self, user):
        """
        Deactivates the SIAE membership of a member (reference held by self)
        `user` is the admin updating this user (`updated_by` field)
        """
        self.is_active = False
        self.updated_by = user
        return False

    def set_admin_role(self, active, user):
        """
        Set admin role for the given user.
        `user` is the admin updating this user (`updated_by` field)
        """
        self.is_siae_admin = active
        self.updated_by = user


class SiaeJobDescriptionQuerySet(models.QuerySet):
    def with_job_applications_count(self, filters=None):
        if filters:
            filters = Q(**filters)

        return self.annotate(
            job_applications_count=Count(
                "jobapplication",
                filter=filters,
            ),
        )

    def with_annotation_is_popular(self):
        # Avoid an infinite loop
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

    # This field is stored for reference but never actually used.
    # Siaes in ASP's "Vue Structure" not only have a "SIRET actualisé",
    # which is the main SIRET we store in `siae.siret` and which often changes
    # over time e.g. when the siae moves to a new location, but they also
    # have a second SIRET field called "SIRET à la signature" in this export.
    # This field is almost unique (one exception, see unique_together clause below)
    # and is almost constant over time, at least much more than the "SIRET actualisé".
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
