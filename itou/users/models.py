from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from allauth.utils import generate_unique_username

from itou.approvals.models import ApprovalsWrapper
from itou.approvals.models import PoleEmploiApproval
from itou.utils.validators import validate_pole_emploi_id


class User(AbstractUser):
    """
    Custom user model.

    Default fields are listed here:
    https://github.com/django/django/blob/972eef6b9060aee4a092bedee38a7775fbbe5d0b/django/contrib/auth/models.py#L289

    Auth is managed with django-allauth.

    To retrieve SIAEs this user belongs to:
        self.siae_set.all()
        self.siaemembership_set.all()

    To retrieve prescribers this user belongs to:
        self.prescriberorganization_set.all()
        self.prescribermembership_set.all()
    """

    birthdate = models.DateField(
        verbose_name=_("Date de naissance"), null=True, blank=True
    )
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=20, blank=True)

    is_job_seeker = models.BooleanField(
        verbose_name=_("Demandeur d'emploi"), default=False
    )
    is_prescriber = models.BooleanField(verbose_name=_("Prescripteur"), default=False)
    is_siae_staff = models.BooleanField(
        verbose_name=_("Employeur (SIAE)"), default=False
    )
    pole_emploi_id = models.CharField(
        verbose_name=_("Identifiant Pôle emploi"),
        help_text=_("7 chiffres suivis d'une 1 lettre ou d'un chiffre."),
        max_length=8,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
        blank=True,
    )
    created_by = models.ForeignKey(
        "self",
        verbose_name=_("Créé par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def save(self, *args, **kwargs):
        already_exists = bool(self.pk)
        # There is no unicity constraint on `email` at the DB level.
        # It's in anticipation of other authentication methods to
        # authenticate against something else, e.g. username/password.
        if (
            not already_exists
            and self.email
            and User.objects.filter(email=self.email).exists()
        ):
            raise ValidationError(_("Cet e-mail existe déjà."))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    @property
    def approvals_wrapper(self):
        if not self.is_job_seeker:
            return None
        return ApprovalsWrapper(self)

    @property
    def has_eligibility_diagnosis(self):
        """
        Returns True if a diagnosis exists, False otherwise.
        The existence of a valid `PoleEmploiApproval` implies that a diagnosis
        has been made outside of Itou.
        """
        return self.is_job_seeker and (
            self.eligibility_diagnoses.exists()
            or PoleEmploiApproval.objects.find_for(
                self.first_name, self.last_name, self.birthdate
            )
            .valid()
            .exists()
        )

    def get_eligibility_diagnosis(self):
        if not self.is_job_seeker:
            return None
        return self.eligibility_diagnoses.select_related(
            "author", "author_siae", "author_prescriber_organization"
        ).latest("-created_at")

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
        username = generate_unique_username(
            [fields["first_name"], fields["last_name"], fields["email"]]
        )
        fields["is_job_seeker"] = True
        fields["created_by"] = proxy_user
        user = cls.objects.create_user(
            username,
            email=fields.pop("email"),
            password=cls.objects.make_random_password(),
            **fields
        )
        return user


def get_allauth_account_user_display(user):
    return user.email
