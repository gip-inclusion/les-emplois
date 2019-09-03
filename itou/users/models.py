from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom user model.

    Default fields are listed here:
    https://github.com/django/django/blob/832369/django/contrib/auth/models.py#L290

    Auth is managed with django-allauth.

    To retrieve SIAEs this user belongs to:
        self.siae_set.all()
        self.siaemembership_set.all()

    To retrieve prescribers this user belongs to:
        self.prescriber_set.all()
        self.prescribermembership_set.all()
    """

    birthdate = models.DateField(
        verbose_name=_("Date de naissance"), null=True, blank=True
    )
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=10, blank=True)

    is_job_seeker = models.BooleanField(
        verbose_name=_("Demandeur d'emploi"), default=False
    )
    is_prescriber_staff = models.BooleanField(
        verbose_name=_("Prescripteur"), default=False
    )
    is_siae_staff = models.BooleanField(
        verbose_name=_("Employeur (SIAE)"), default=False
    )

    def __str__(self):
        return self.email

    def can_postulate(self):
        return self.birthdate and self.phone


def get_allauth_account_user_display(user):
    return user.email
