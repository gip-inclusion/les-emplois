import datetime
import random

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import models
from django.db.models import F, Prefetch
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _

from itou.utils.address.models import AddressMixin
from itou.utils.emails import get_email_message
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_naf, validate_siret


class SiaeQuerySet(models.QuerySet):
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

    def shuffle(self):
        """
        Quick and dirty solution to shuffle results with a
        determistic seed which changes every day.

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
        return self.annotate(shuffled_rank=shuffle_expression).order_by("shuffled_rank")


class ActiveSiaeManager(models.Manager.from_queryset(SiaeQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


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
    KIND_GEIQ = "GEIQ"
    KIND_EA = "EA"
    KIND_EATT = "EATT"

    KIND_CHOICES = (
        (KIND_EI, _("Entreprise d'insertion")),  # Regroupées au sein de la fédération des entreprises d'insertion.
        (KIND_AI, _("Association intermédiaire")),
        (KIND_ACI, _("Atelier chantier d'insertion")),
        (KIND_ETTI, _("Entreprise de travail temporaire d'insertion")),
        (KIND_GEIQ, _("Groupement d'employeurs pour l'insertion et la qualification")),
        (KIND_EA, _("Entreprise adaptée")),
        (KIND_EATT, _("Entreprise adaptée de travail temporaire")),
    )

    SOURCE_ASP = "ASP"
    SOURCE_GEIQ = "GEIQ"
    SOURCE_USER_CREATED = "USER_CREATED"

    SOURCE_CHOICES = (
        (SOURCE_ASP, _("Export ASP")),
        (SOURCE_GEIQ, _("Export GEIQ")),
        (SOURCE_USER_CREATED, _("Utilisateur")),
    )

    ELIGIBILITY_REQUIRED_KINDS = [KIND_EI, KIND_AI, KIND_ACI, KIND_ETTI]

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret], db_index=True)
    naf = models.CharField(verbose_name=_("Naf"), max_length=5, validators=[validate_naf], blank=True)
    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=KIND_CHOICES, default=KIND_EI)
    name = models.CharField(verbose_name=_("Nom"), max_length=255)
    # `brand` (or `enseigne` in French) is used to override `name` if needed.
    brand = models.CharField(verbose_name=_("Enseigne"), max_length=255, blank=True)
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=20, blank=True)
    email = models.EmailField(verbose_name=_("E-mail"), blank=True)
    # All siaes without any existing user require this auth_email
    # for the siae secure signup process to even be possible.
    # Comes from external exports (ASP, GEIQ...)
    auth_email = models.EmailField(verbose_name=_("E-mail d'authentification"), blank=True)
    website = models.URLField(verbose_name=_("Site web"), blank=True)
    description = models.TextField(verbose_name=_("Description"), blank=True)

    # An active structure means:
    # - (for SIAE) it is authorized by ASP ("conventionnée" in French).
    # - (for non SIAE) it is allowed to use the service.
    is_active = models.BooleanField(
        verbose_name=_("Active"),
        default=True,
        help_text=_(
            "Précise pour les SIAE si la structure a un "
            "conventionnement valide à ce jour et pour les autres "
            "types de structures si elle est autorisée à utiliser "
            "la plateforme."
        ),
    )
    # This deactivation date is not enforced and only stored for
    # information, for admin and/or metabase uses.
    active_until = models.DateTimeField(verbose_name=_("Date de désactivation"), blank=True, null=True)
    # When itou staff manually reactivates an inactive siae, store who did it and when.
    reactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Réactivée manuellement en dernier par"),
        related_name="reactivated_siae_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reactivated_at = models.DateTimeField(
        verbose_name=_("Date de dernière réactivation manuelle"), blank=True, null=True
    )

    source = models.CharField(
        verbose_name=_("Source de données"), max_length=20, choices=SOURCE_CHOICES, default=SOURCE_ASP
    )
    # In the case of exports from the ASP, this external_id is the internal ID of
    # the siae objects in ASP's own database. These are supposed to never change,
    # so as long as the ASP keeps including this field in all their exports,
    # it will be easy for us to accurately match data between exports.
    # Note that this external_id unicity is based on SIRET only.
    # In other words, if an EI and a ACI share the same SIRET, they also
    # share the same external_id in ASP's own database.
    external_id = models.IntegerField(verbose_name=_("ID externe"), null=True, blank=True)

    jobs = models.ManyToManyField(
        "jobs.Appellation", verbose_name=_("Métiers"), through="SiaeJobDescription", blank=True
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name=_("Membres"), through="SiaeMembership", blank=True
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
    parent = models.ForeignKey(
        "self",
        verbose_name=_("Structure mère"),
        related_name="children",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Ability to block new job applications
    block_job_applications = models.BooleanField(verbose_name=_("Blocage des candidatures"), default=False)
    job_applications_blocked_at = models.DateTimeField(
        verbose_name=_("Date du dernier blocage de candidatures"), blank=True, null=True
    )

    objects = models.Manager.from_queryset(SiaeQuerySet)()
    active = ActiveSiaeManager()

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
    def is_subject_to_eligibility_rules(self):
        return self.kind in self.ELIGIBILITY_REQUIRED_KINDS

    def get_card_url(self):
        return reverse("siaes_views:card", kwargs={"siae_id": self.pk})

    @property
    def root_parent(self):
        if self.parent:
            return self.parent.root_parent
        return self

    @property
    def active_members(self):
        return self.members.filter(is_active=True)

    @property
    def active_admin_members(self):
        return self.active_members.filter(siaemembership__is_siae_admin=True, siaemembership__siae=self)

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


class SiaeMembership(models.Model):
    """Intermediary model between `User` and `Siae`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name=_("Date d'adhésion"), default=timezone.now)
    is_siae_admin = models.BooleanField(verbose_name=_("Administrateur de la SIAE"), default=False)


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
