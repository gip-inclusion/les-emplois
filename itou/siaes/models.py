import datetime
import random

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import models
from django.db.models import F, Prefetch, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _

from itou.utils.address.departments import DEPARTMENTS, DEPARTMENTS_OPEN_FOR_NON_ETTI_SIAES
from itou.utils.address.models import AddressMixin
from itou.utils.emails import get_email_message
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_af_number, validate_convention_number, validate_naf, validate_siret


class SiaeQuerySet(models.QuerySet):
    def active(self):
        # `~` means NOT, similarly to dataframes.
        return self.select_related("convention").filter(
            # GEIQ, EA... have no convention logic and thus are always active.
            ~Q(kind__in=Siae.ELIGIBILITY_REQUIRED_KINDS)
            # User created siaes and staff created siaes do not yet
            # have convention logic and thus are always active.
            | Q(source__in=[Siae.SOURCE_USER_CREATED, Siae.SOURCE_STAFF_CREATED])
            # A siae of ASP source is active if and only if it has an active convention.
            | Q(convention__is_active=True)
        )

    def active_or_in_grace_period(self):
        now = timezone.now()
        grace_period = timezone.timedelta(days=SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)
        return self.select_related("convention").filter(
            ~Q(kind__in=Siae.ELIGIBILITY_REQUIRED_KINDS)
            | Q(source__in=[Siae.SOURCE_USER_CREATED, Siae.SOURCE_STAFF_CREATED])
            | Q(convention__is_active=True)
            # Here we include siaes experiencing their grace period as well.
            | Q(convention__deactivated_at__gte=now - grace_period)
        )

    def within(self, point, distance_km):
        return (
            self.filter(coords__distance_lte=(point, D(km=distance_km)))
            .annotate(distance=Distance("coords", point))
            .order_by("distance")
        )

    def prefetch_job_description_through(self, **kwargs):
        job_description_through = Prefetch(
            "job_description_through",
            queryset=(SiaeJobDescription.objects.filter(**kwargs).select_related("appellation__rome")),
        )
        return self.prefetch_related(job_description_through)

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
    KIND_ETTI = "ETTI"
    KIND_EITI = "EITI"
    KIND_GEIQ = "GEIQ"
    KIND_EA = "EA"
    KIND_EATT = "EATT"

    KIND_CHOICES = (
        (KIND_EI, _("Entreprise d'insertion")),  # Regroupées au sein de la fédération des entreprises d'insertion.
        (KIND_AI, _("Association intermédiaire")),
        (KIND_ACI, _("Atelier chantier d'insertion")),
        (KIND_ETTI, _("Entreprise de travail temporaire d'insertion")),
        (KIND_EITI, _("Entreprise d'insertion par le travail indépendant")),
        (KIND_GEIQ, _("Groupement d'employeurs pour l'insertion et la qualification")),
        (KIND_EA, _("Entreprise adaptée")),
        (KIND_EATT, _("Entreprise adaptée de travail temporaire")),
    )

    SOURCE_ASP = "ASP"
    SOURCE_GEIQ = "GEIQ"
    SOURCE_USER_CREATED = "USER_CREATED"
    SOURCE_STAFF_CREATED = "STAFF_CREATED"

    SOURCE_CHOICES = (
        (SOURCE_ASP, _("Export ASP")),
        (SOURCE_GEIQ, _("Export GEIQ")),
        (SOURCE_USER_CREATED, _("Utilisateur (Antenne)")),
        (SOURCE_STAFF_CREATED, _("Staff Itou")),
    )

    # https://code.travail.gouv.fr/code-du-travail/l5132-4
    # https://www.legifrance.gouv.fr/eli/loi/2018/9/5/2018-771/jo/article_83
    ELIGIBILITY_REQUIRED_KINDS = [KIND_EI, KIND_AI, KIND_ACI, KIND_ETTI, KIND_EITI]

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret], db_index=True)
    naf = models.CharField(verbose_name=_("Naf"), max_length=5, validators=[validate_naf], blank=True)
    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=KIND_CHOICES, default=KIND_EI)
    name = models.CharField(verbose_name=_("Nom"), max_length=255)
    # `brand` (or `enseigne` in French) is used to override `name` if needed.
    brand = models.CharField(verbose_name=_("Enseigne"), max_length=255, blank=True)
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=20, blank=True)
    email = models.EmailField(verbose_name=_("E-mail"), blank=True)
    # All siaes without any existing user require this auth_email
    # for the siae secure signup process to be possible.
    # Comes from external exports (ASP, GEIQ...)
    auth_email = models.EmailField(verbose_name=_("E-mail d'authentification"), blank=True)
    website = models.URLField(verbose_name=_("Site web"), blank=True)
    description = models.TextField(verbose_name=_("Description"), blank=True)

    source = models.CharField(
        verbose_name=_("Source de données"), max_length=20, choices=SOURCE_CHOICES, default=SOURCE_ASP
    )

    jobs = models.ManyToManyField(
        "jobs.Appellation", verbose_name=_("Métiers"), through="SiaeJobDescription", blank=True
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Membres"),
        through="SiaeMembership",
        through_fields=("siae", "user"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Créé par"),
        related_name="created_siae_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True)

    # Ability to block new job applications
    block_job_applications = models.BooleanField(verbose_name=_("Blocage des candidatures"), default=False)
    job_applications_blocked_at = models.DateTimeField(
        verbose_name=_("Date du dernier blocage de candidatures"), blank=True, null=True
    )

    # A convention can only be deleted if it is no longer linked to any siae.
    convention = models.ForeignKey(
        "SiaeConvention", on_delete=models.RESTRICT, blank=True, null=True, related_name="siaes",
    )

    objects = models.Manager.from_queryset(SiaeQuerySet)()

    class Meta:
        verbose_name = _("Structure d'insertion par l'activité économique")
        verbose_name_plural = _("Structures d'insertion par l'activité économique")
        unique_together = ("siret", "kind")

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
        if self.kind not in Siae.ELIGIBILITY_REQUIRED_KINDS:
            # GEIQ, EA... have no convention logic and thus are always active.
            return True
        if self.source in [Siae.SOURCE_USER_CREATED, Siae.SOURCE_STAFF_CREATED]:
            # User created siaes and staff created siaes do not yet have convention logic.
            return True
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
        return self.members(is_active=True, siaemembership__is_active=False)

    @property
    def active_admin_members(self):
        """
        Active admin members:
        active user/admin in this context means both:
        * user.is_active: user is able to do something on the platform
        * user.membership.is_active: is a member of this structure
        """
        return self.active_members.filter(siaemembership__is_siae_admin=True, siaemembership__siae=self,)

    @property
    def signup_magic_link(self):
        return reverse(
            "signup:siae", kwargs={"encoded_siae_id": self.get_encoded_siae_id(), "token": self.get_token()}
        )

    def get_encoded_siae_id(self):
        return urlsafe_base64_encode(force_bytes(self.pk))

    def get_token(self):
        return siae_signup_token_generator.make_token(self)

    def new_signup_warning_email_to_existing_members(self, user):
        """
        Send a warning fyi-only email to all existing users of the siae
        about a new user signup.
        """
        to = [u.email for u in self.active_members]
        context = {"new_user": user, "siae": self}
        subject = "siaes/email/new_signup_warning_email_to_existing_members_subject.txt"
        body = "siaes/email/new_signup_warning_email_to_existing_members_body.txt"
        return get_email_message(to, context, subject, body)

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

    def new_member_deactivation_email(self, user):
        """
        Send email when an admin of the structure disable the membership of a given user (deactivation).
        """
        to = [user.email]
        context = {"siae": self}
        subject = "siaes/email/new_member_deactivation_email_subject.txt"
        body = "siaes/email/new_member_deactivation_email_body.txt"
        return get_email_message(to, context, subject, body)

    def new_member_activation_email(self, user):
        """
        Send email when an admin of the structure reactivate the membership of a given user.
        """
        to = [user.email]
        context = {"siae": self}
        subject = "siaes/email/new_member_activation_email_subject.txt"
        body = "siaes/email/new_member_activation_email_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def open_departments(self):
        if self.kind == self.KIND_ETTI:
            return DEPARTMENTS
        return {dpt: DEPARTMENTS[dpt] for dpt in sorted(DEPARTMENTS_OPEN_FOR_NON_ETTI_SIAES)}

    @property
    def is_in_open_department(self):
        return self.department in self.open_departments

    @property
    def grace_period_end_date(self):
        return self.convention.deactivated_at + timezone.timedelta(
            days=SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS
        )

    @property
    def grace_period_has_expired(self):
        return not self.is_active and timezone.now() > self.grace_period_end_date


class SiaeMembership(models.Model):
    """Intermediary model between `User` and `Siae`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name=_("Date d'adhésion"), default=timezone.now)
    is_siae_admin = models.BooleanField(verbose_name=_("Administrateur de la SIAE"), default=False)
    is_active = models.BooleanField(_("Rattachement actif"), default=True)
    updated_at = models.DateTimeField(verbose_name=_("Date de mise à jour"), null=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="siae_membership_updated_by",
        null=True,
        on_delete=models.CASCADE,
        verbose_name=_("Mis à jour par"),
    )

    class Meta:
        unique_together = ("user_id", "siae_id")

    def toggle_user_membership(self, user):
        """
        Toggles the SIAE membership of a member (reference held by self)
        `user` is the admin updating this user (`updated_by` field)
        """
        assert user

        self.is_active = not self.is_active
        self.updated_at = timezone.now()
        self.updated_by = user
        return self.is_active


class SiaeJobDescription(models.Model):
    """
    A job description of a position in an SIAE.
    Intermediary model between `jobs.Appellation` and `Siae`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    MAX_UI_RANK = 32767

    appellation = models.ForeignKey("jobs.Appellation", on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE, related_name="job_description_through")
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True, db_index=True)
    is_active = models.BooleanField(verbose_name=_("Recrutement ouvert"), default=True)
    custom_name = models.CharField(verbose_name=_("Nom personnalisé"), blank=True, max_length=255)
    description = models.TextField(verbose_name=_("Description"), blank=True)
    # TODO: this will be used to order job description in UI.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)

    class Meta:
        verbose_name = _("Fiche de poste")
        verbose_name_plural = _("Fiches de postes")
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
    A SiaeConvention encapsulates the logic to decide whether a Siae is active.

    A SiaeConvention is typically shared by one siae of source ASP
    and zero or several user created siaes ("Antennes").

    A SiaeConvention has many SiaeFinancialAnnex related objects.
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
        (KIND_EI, _("Entreprise d'insertion")),
        (KIND_AI, _("Association intermédiaire")),
        (KIND_ACI, _("Atelier chantier d'insertion")),
        (KIND_ETTI, _("Entreprise de travail temporaire d'insertion")),
        (KIND_EITI, _("Entreprise d'insertion par le travail indépendant")),
    )

    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=KIND_CHOICES, default=KIND_EI)
    siret_signature = models.CharField(
        verbose_name=_("Siret à la signature"), max_length=14, validators=[validate_siret], db_index=True,
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
        verbose_name=_("Active"),
        default=True,
        help_text=_(
            "Précise si la convention est active c.a.d. si elle a au moins une annexe financière valide à ce jour."
        ),
        db_index=True,
    )
    # Grace period starts from this date.
    deactivated_at = models.DateTimeField(
        verbose_name=_("Date de  désactivation et début de délai de grâce"), blank=True, null=True, db_index=True,
    )
    # When itou staff manually reactivates an inactive convention, store who did it and when.
    reactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Réactivée manuellement par"),
        related_name="reactivated_siae_convention_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reactivated_at = models.DateTimeField(verbose_name=_("Date de réactivation manuelle"), blank=True, null=True)

    # Internal ID of siaes à la ASP. This ID is supposed to never change,
    # so as long as the ASP keeps including this field in all their exports,
    # it will be easy for us to accurately sync data between exports.
    # Note that this asp_id unicity is based on SIRET only.
    # In other words, if an EI and a ACI share the same SIRET, they also
    # share the same asp_id in ASP's own database.
    # In this example a single siae à la ASP corresponds to two siaes à la Itou.
    asp_id = models.IntegerField(verbose_name=_("ID ASP de la SIAE"), db_index=True,)

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True)

    class Meta:
        verbose_name = _("Convention")
        verbose_name_plural = _("Conventions")
        unique_together = (
            ("asp_id", "kind"),
            # Unfortunately the (siret_signature, kind) couple is not unique,
            # as the two asp_ids 2455 and 4281 share the same values.
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
        (STATE_VALID, _("Validée")),
        (STATE_PROVISIONAL, _("Provisoire (valide)")),
        (STATE_ARCHIVED, _("Archivée (invalide)")),
        (STATE_CANCELLED, _("Annulée")),
        (STATE_ENTERED, _("Saisie (invalide)")),
        (STATE_DRAFT, _("Brouillon (invalide)")),
        (STATE_CLOSED, _("Cloturée (invalide)")),
        (STATE_REJECTED, _("Rejetée")),
    )

    STATES_ACTIVE = [STATE_VALID, STATE_PROVISIONAL]
    STATES_INACTIVE = [STATE_ARCHIVED, STATE_CANCELLED, STATE_ENTERED, STATE_DRAFT, STATE_CLOSED, STATE_REJECTED]
    STATES_ALL = STATES_ACTIVE + STATES_INACTIVE

    number = models.CharField(
        verbose_name=_("Numéro d'annexe financière"),
        max_length=17,
        validators=[validate_af_number],
        unique=True,
        db_index=True,
    )
    # This field is at SiaeFinancialAnnex level and not at SiaeConvention level
    # because one SiaeConvention can have financial annexes with different convention numbers.
    convention_number = models.CharField(
        verbose_name=_("Numéro de convention"), max_length=19, validators=[validate_convention_number], db_index=True
    )
    state = models.CharField(verbose_name=_("Etat"), max_length=20, choices=STATE_CHOICES,)
    start_at = models.DateTimeField(verbose_name=_("Date de début d'effet"))
    end_at = models.DateTimeField(verbose_name=_("Date de fin d'effet"))

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True)

    # A financial annex cannot exist without a convention, and
    # deleting a convention will delete all its financial annexes.
    convention = models.ForeignKey("SiaeConvention", on_delete=models.CASCADE, related_name="financial_annexes",)

    class Meta:
        verbose_name = _("Annexe financière")
        verbose_name_plural = _("Annexes financières")

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def is_active(self):
        return self.state in SiaeFinancialAnnex.STATES_ACTIVE and self.end_at > timezone.now()
