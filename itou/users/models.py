from functools import partial
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from allauth.utils import generate_unique_username

from itou.utils.tokens import generate_random_token


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

    created_by = models.ForeignKey(
        "self",
        verbose_name=_("Créé par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # Sometimes used as a hard-to-guess user id.
    uuid = models.UUIDField(
        default=uuid.uuid4, editable=False, db_index=True, unique=True
    )

    def __str__(self):
        return self.email

    def is_admin_of_siae(self, siae):
        return self.siaemembership_set.filter(siae=siae, is_siae_admin=True).exists()

    @property
    def has_eligibility_diagnosis(self):
        return self.is_job_seeker and self.eligibility_diagnoses.exists()

    def get_eligibility_diagnosis(self):
        if not self.is_job_seeker:
            return None
        return self.eligibility_diagnoses.select_related(
            "author", "author_siae", "author_prescriber_organization"
        ).latest("-created_at")

    def get_approval(self):
        if not self.is_job_seeker or not self.approvals.exists():
            return None
        return self.approvals.latest("-created_at")

    def has_valid_approval(self):
        if not self.is_job_seeker:
            return False
        now = timezone.now().date()
        return (
            self.approvals.filter(start_at__lte=now, end_at__gte=now).exists()
            | self.approvals.filter(start_at__gte=now).exists()
        )

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

    def create_pending_validation(self):
        if hasattr(self, "uservalidation"):
            raise RuntimeError("Validation already exists.")
        validation = UserValidation(user=self)
        validation.save()

    @property
    def has_pending_validation(self):
        return hasattr(self, "uservalidation") and not self.uservalidation.is_validated


def get_allauth_account_user_display(user):
    return user.email


class UserValidation(models.Model):
    """
    Validation of new user signups by authoritative users.
    Used for SIAE only at the moment:
    - when a new siae user joins an existing siae with existing
      admin user(s), the new user is pending validation and an email
      is sent to the existing admin user(s) to validate it.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True
    )
    secret = models.CharField(
        verbose_name=_("Secret du magic link"),
        help_text=_(
            "Code secret présent dans le magic link permettant la validation sécurisée d'un nouvel utilisateur."
        ),
        max_length=32,
        default=partial(generate_random_token, n=32),
        unique=True,
    )
    created_at = models.DateTimeField(
        verbose_name=_("Date de création"), default=timezone.now
    )
    updated_at = models.DateTimeField(
        verbose_name=_("Date de modification"), blank=True, null=True
    )
    sent_to_email = models.EmailField(verbose_name=_("Demandée à cet email"))
    is_validated = models.BooleanField(verbose_name=_("Est validée"), default=False)
    validated_at = models.DateTimeField(
        verbose_name=_("Date de validation"), blank=True, null=True
    )

    class Meta:
        verbose_name = _("Validation de compte utilisateur")
        verbose_name_plural = _("Validations de compte utilisateur")

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def get_magic_link(self):
        return reverse(
            "signup:validation",
            kwargs={"user_uuid": self.user.uuid, "secret": self.secret},
        )

    def complete(self):
        if self.is_validated:
            raise RuntimeError("Validation is already validated. See the irony?")
        self.user.is_active = True
        self.user.save()
        self.is_validated = True
        self.validated_at = timezone.now()
        self.save()
