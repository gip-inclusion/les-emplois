from allauth.utils import generate_unique_username
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import CIEmailField
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from itou.approvals.models import ApprovalsWrapper
from itou.asp.models import AllocationDuration, Commune, EducationLevel, LaneExtension, LaneType
from itou.utils.address.departments import department_from_postcode
from itou.utils.address.models import AddressMixin
from itou.utils.validators import validate_birthdate, validate_pole_emploi_id


class User(AbstractUser, AddressMixin):
    """
    Custom user model.

    Default fields are listed here:
    https://github.com/django/django/blob/f3901b5899d746dc5b754115d94ce9a045b4db0a/django/contrib/auth/models.py#L321

    Auth is managed with django-allauth.

    To retrieve SIAEs this user belongs to:
        self.siae_set.all()
        self.siaemembership_set.all()

    To retrieve prescribers this user belongs to:
        self.prescriberorganization_set.all()
        self.prescribermembership_set.all()


    The User model has a "companion" model in the `external_data` app,
    for third-party APIs data import concerns (class `JobSeekerExternalData`).

    At the moment, only users (job seekers) connected via PE Connect
    have external data stored.

    More details in `itou.external_data.models` module
    """

    # Used for validation of birth country / place
    INSEE_CODE_FRANCE = "100"

    REASON_FORGOTTEN = "FORGOTTEN"
    REASON_NOT_REGISTERED = "NOT_REGISTERED"
    REASON_CHOICES = (
        (REASON_FORGOTTEN, _("Identifiant Pôle emploi oublié")),
        (REASON_NOT_REGISTERED, _("Non inscrit auprès de Pôle emploi")),
    )

    ERROR_EMAIL_ALREADY_EXISTS = _("Cet e-mail existe déjà.")
    ERROR_MUST_PROVIDE_BIRTH_PLACE = _(
        "Si le pays de naissance est la France, la commune de naissance est obligatoire"
    )

    class Title(models.TextChoices):
        M = "M", _("Monsieur")
        MME = "MME", _("Madame")

    title = models.CharField(max_length=3, verbose_name=_("Civilité"), null=True, blank=True, choices=Title.choices)

    birthdate = models.DateField(
        verbose_name=_("Date de naissance"), null=True, blank=True, validators=[validate_birthdate]
    )
    birth_place = models.ForeignKey(
        "asp.Commune", verbose_name=_("Commune de naissance"), null=True, blank=True, on_delete=models.SET_NULL
    )
    birth_country = models.ForeignKey(
        "asp.Country", verbose_name=_("Pays de naissance"), null=True, blank=True, on_delete=models.SET_NULL
    )
    email = CIEmailField(
        _("email address"),
        blank=True,
        db_index=True,
        # Empty values are stored as NULL if both `null=True` and `unique=True` are set.
        # This avoids unique constraint violations when saving multiple objects with blank values.
        null=True,
        unique=True,
    )
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=20, blank=True)

    is_job_seeker = models.BooleanField(verbose_name=_("Demandeur d'emploi"), default=False)
    is_prescriber = models.BooleanField(verbose_name=_("Prescripteur"), default=False)
    is_siae_staff = models.BooleanField(verbose_name=_("Employeur (SIAE)"), default=False)
    is_stats_vip = models.BooleanField(verbose_name=_("Pilotage"), default=False)

    # The two following Pôle emploi fields are reserved for job seekers.
    # They are used in the process of delivering an approval.
    # They depend on each other: one or the other must be filled but not both.

    # Pôle emploi ID is not guaranteed to be unique.
    # At least, we haven't received any confirmation of its uniqueness.
    # It looks like it pre-dates the national merger and may be unique
    # by user and by region…
    pole_emploi_id = models.CharField(
        verbose_name=_("Identifiant Pôle emploi"),
        help_text=_("7 chiffres suivis d'une 1 lettre ou d'un chiffre."),
        max_length=8,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
        blank=True,
    )
    lack_of_pole_emploi_id_reason = models.CharField(
        verbose_name=_("Pas d'identifiant Pôle emploi ?"),
        help_text=mark_safe(
            _(
                "Indiquez la raison de l'absence d'identifiant Pôle emploi.<br>"
                "Renseigner l'identifiant Pôle emploi des candidats inscrits "
                "permet d'instruire instantanément votre demande.<br>"
                "Dans le cas contraire un délai de deux jours est nécessaire "
                "pour effectuer manuellement les vérifications d’usage."
            )
        ),
        max_length=30,
        choices=REASON_CHOICES,
        blank=True,
    )
    resume_link = models.URLField(max_length=500, verbose_name=_("Lien vers un CV"), blank=True)
    has_completed_welcoming_tour = models.BooleanField(verbose_name=_("Parcours de bienvenue effectué"), default=False)

    created_by = models.ForeignKey(
        "self", verbose_name=_("Créé par"), on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return self.email

    def clean(self):
        if self.birth_country and self.birth_country.code == self.INSEE_CODE_FRANCE and not self.birth_place:
            raise ValidationError(self.ERROR_MUST_PROVIDE_BIRTH_PLACE)

    def save(self, *args, **kwargs):
        # Update department from postal code (if possible).
        self.department = department_from_postcode(self.post_code)
        self.validate_unique()
        super().save(*args, **kwargs)

    @cached_property
    def approvals_wrapper(self):
        if not self.is_job_seeker:
            return None
        return ApprovalsWrapper(self)

    @property
    def is_handled_by_proxy(self):
        if self.is_job_seeker and self.created_by and not self.last_login:
            return True
        return False

    @cached_property
    def is_peamu(self):
        social_accounts = self.socialaccount_set.all()
        # We have to do all this in python to benefit from prefetch_related.
        return len([sa for sa in social_accounts if sa.provider == "peamu"]) >= 1

    @cached_property
    def peamu_id_token(self):
        if not self.is_peamu:
            return None
        return self.socialaccount_set.filter(provider="peamu").get().extra_data["id_token"]

    @property
    def is_prescriber_with_org(self):
        return self.is_prescriber and self.prescribermembership_set.filter(is_active=True).exists()

    @property
    def is_prescriber_with_authorized_org(self):
        return (
            self.is_prescriber
            and self.prescriberorganization_set.filter(is_authorized=True, members__is_active=True).exists()
        )

    @property
    def has_external_data(self):
        return self.is_job_seeker and hasattr(self, "jobseekerexternaldata")

    def joined_recently(self):
        time_since_date_joined = timezone.now() - self.date_joined
        return time_since_date_joined.days < 7

    @property
    def has_pole_emploi_email(self):
        return self.email and self.email.endswith(settings.POLE_EMPLOI_EMAIL_SUFFIX)

    @property
    def is_siae_staff_with_siae(self):
        """
        Useful to identify users deactivated as member of a SIAE
        and without any membership left.
        They are in a "dangling" status: still active (membership-wise) but unable to login
        because not member of any SIAE.
        """
        return self.is_siae_staff and self.siaemembership_set.filter(is_active=True).exists()

    @cached_property
    def last_accepted_job_application(self):
        if not self.is_job_seeker:
            return None
        return self.job_applications.accepted().latest("created_at")

    def last_hire_was_made_by_siae(self, siae):
        if not self.is_job_seeker:
            return False
        return self.last_accepted_job_application.to_siae == siae

    @classmethod
    def create_job_seeker_by_proxy(cls, proxy_user, **fields):
        """
        Used when a "prescriber" user creates another user of kind "job seeker".

        Minimum required keys in `fields` are:
            {
                "email": "foo@foo.com",
                "first_name": "Foo",
                "last_name": "Foo",
            }
        """
        username = generate_unique_username([fields["first_name"], fields["last_name"], fields["email"]])
        fields["is_job_seeker"] = True
        fields["created_by"] = proxy_user
        user = cls.objects.create_user(
            username, email=fields.pop("email"), password=cls.objects.make_random_password(), **fields
        )
        return user

    @classmethod
    def email_already_exists(cls, email, exclude_pk=None):
        """
        RFC 5321 Part 2.4 states that only the domain portion of an email
        is case-insensitive. Consider toto@toto.com and TOTO@toto.com as
        the same email.
        """
        queryset = cls.objects.filter(email__iexact=email)
        if exclude_pk:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.exists()

    @staticmethod
    def clean_pole_emploi_fields(pole_emploi_id, lack_of_pole_emploi_id_reason):
        """
        Only for users with the `is_job_seeker` flag set to True.
        Validate Pôle emploi fields that depend on each other: one or
        the other must be filled but not both.
        It must be used in forms and modelforms that manipulate job seekers.
        """
        if (pole_emploi_id and lack_of_pole_emploi_id_reason) or (
            not pole_emploi_id and not lack_of_pole_emploi_id_reason
        ):
            raise ValidationError(_("Renseignez soit un identifiant Pôle emploi, soit la raison de son absence."))


def get_allauth_account_user_display(user):
    return user.email


class JobSeekerProfile(models.Model):
    """
    Specific information about the job seeker

    Instead of augmenting the 'User' model, additional data is collected in a "profile" object.

    This user profile has 2 main parts:

    1 - Job seeker "administrative" situation

    These fields are part of the requires fields for EmployeeRecord processing:
    - education level
    - various social allowances flags and duration

    2- Job seeker address in HEXA address format:

    The SNA (Service National de l'Adresse) has several certification / validation
    norms to verify french addresses:
    - Hexacle: house number level
    - Hexaposte: zip code level
    - Hexavia: street level
    + others

    For the employee record domain, this means that the job seeker address has to be
    formatted in a very specific way to be accepted as valid by ASP backend.

    These conversions and formatting processes are almost automatic,
    but absolutely not 100% error-proof.

    Formatted addresses are stored in this model, avoiding multiple calls to the
    reverse geocoding API at processing time.

    This kind of address are at the moment only used by the employee_record app,
    but their usage could be extended to other domains should the need arise.

    Note that despite the name, addresses of this model are not fully compliant
    with Hexa norms (but compliant enough to be accepted by ASP backend).
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        verbose_name=_("Demandeur d'emploi"),
        related_name="jobseeker_profile",
    )

    education_level = models.CharField(
        max_length=2,
        verbose_name=_("Niveau de formation (ASP)"),
        blank=True,
        choices=EducationLevel.choices,
    )

    resourceless = models.BooleanField(verbose_name=_("Sans ressource"), default=False)

    rqth_employee = models.BooleanField(verbose_name=_("Employé RQTH"), default=False)
    oeth_employee = models.BooleanField(verbose_name=_("Employé OETH"), default=False)

    pole_emploi_since = models.CharField(
        max_length=20,
        verbose_name=_("Inscrit à Pôle emploi depuis"),
        blank=True,
        choices=AllocationDuration.choices,
    )

    unemployed_since = models.CharField(
        max_length=20,
        verbose_name=_("Sans emploi depuis"),
        blank=True,
        choices=AllocationDuration.choices,
    )

    rsa_allocation_since = models.CharField(
        max_length=20,
        verbose_name=_("Allocataire du RSA depuis"),
        blank=True,
        choices=AllocationDuration.choices,
    )

    ass_allocation_since = models.CharField(
        max_length=20,
        verbose_name=_("Allocataire de l'ASS depuis"),
        blank=True,
        choices=AllocationDuration.choices,
    )

    aah_allocation_since = models.CharField(
        max_length=20,
        verbose_name=_("Allocataire de l'AAH depuis"),
        blank=True,
        choices=AllocationDuration.choices,
    )

    ata_allocation_since = models.CharField(
        max_length=20,
        verbose_name=_("Allocataire de l'ATA depuis"),
        blank=True,
        choices=AllocationDuration.choices,
    )

    # Jobseeker address in Hexa format

    hexa_lane_number = models.CharField(max_length=10, verbose_name=_("Numéro de la voie"), blank=True)
    hexa_std_extension = models.CharField(
        max_length=1, verbose_name=_("Extension de voie"), null=True, blank=True, choices=LaneExtension.choices
    )
    non_std_extension = models.CharField(
        max_length=10, verbose_name=_("Extension de voie (non-repertoriée)"), blank=True
    )
    hexa_lane_type = models.CharField(
        max_length=4, verbose_name=_("Type de voie"), null=True, blank=True, choices=LaneType.choices
    )
    hexa_lane_name = models.CharField(max_length=120, verbose_name=_("Nom de la voie"), blank=True)
    hexa_post_code = models.CharField(max_length=6, verbose_name=_("Code postal"), blank=True)
    hexa_commune = models.ForeignKey(
        Commune, verbose_name=_("Commune (ref. ASP)"), null=True, on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = _("Profil demandeur d'emploi")
        verbose_name_plural = _("Profils demandeur d'emploi")

    def __str__(self):
        return f"JobSeekerProfile: {self.user}"

    def clean(self):
        if self.resourceless and self.is_employed:
            raise ValidationError(_("La personne n'est pas considérée comme sans ressources si OETH ou RQTH"))

        if self.is_employed and self.unemployed_since:
            raise ValidationError(_("La personne ne peut avoir de période sans emploi si actuellement employée"))

        if self.unemployed_since and self.is_employed:
            raise ValidationError(_("La personne ne peut être considérée comme sans emploi si employée OETH ou RQTH"))

    @property
    def is_employed(self):
        return self.rqth_employee or self.oeth_employee

    @property
    def has_rsa_allocation(self):
        return self.rsa_allocation_since != AllocationDuration.NONE

    @property
    def has_ass_allocation(self):
        return self.ass_allocation_since != AllocationDuration.NONE

    @property
    def has_aah_allocation(self):
        return self.aah_allocation_since != AllocationDuration.NONE

    @property
    def has_ata_allocation(self):
        return self.ata_allocation_since != AllocationDuration.NONE

    @property
    def has_social_allowance(self):
        return self.has_rsa_allocation or self.has_ass_allocation or self.has_aah_allocation or self.has_ata_allocation
