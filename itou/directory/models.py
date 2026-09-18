from django.conf import settings
from django.db import models

from itou.users.enums import UserKind


class DirectoryProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="directory_profile",
        limit_choices_to={"kind": UserKind.PROFESSIONAL},
    )
    is_opted_out = models.BooleanField(
        verbose_name="ne pas apparaître dans l'annuaire des professionnels",
        default=False,
    )

    class Meta:
        verbose_name = "profil de l'annuaire"
        verbose_name_plural = "profils de l'annuaire"

    def __str__(self):
        return f"Profil annuaire de {self.user}"
