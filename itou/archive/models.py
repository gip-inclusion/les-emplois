import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class ArchivedUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date_joined = models.DateField(verbose_name=_("date joined"))
    first_login = models.DateField(verbose_name=_("first login"), blank=True, null=True)
    last_login = models.DateField(verbose_name=_("last login"), blank=True, null=True)
    archived_at = models.DateField(verbose_name="date d'archivage")
    user_signup_kind = models.CharField(
        max_length=50, verbose_name="créé par un utilisateur de type", blank=True, null=True
    )
    department = models.CharField(max_length=3, verbose_name="département", blank=True, null=True)
    title = models.CharField(
        max_length=3,
        verbose_name="civilité",
        blank=True,
        null=True,
    )
    identity_provider = models.CharField(max_length=20, verbose_name="fournisseur d'identité (SSO)")
    kind = models.CharField(max_length=20, verbose_name="type")

    class Meta:
        verbose_name = "Utilisateur archivé"
        verbose_name_plural = "Utilisateurs archivés"
        ordering = ["-archived_at"]


class ArchivedJobSeekerProfile(models.Model):
    user = models.OneToOneField(
        ArchivedUser,
        on_delete=models.CASCADE,
        primary_key=True,
        verbose_name="demandeur d'emploi",
        related_name="jobseeker_profile",
    )
    had_pole_emploi_id = models.BooleanField(verbose_name="ID Pôle emploi")
    had_nir = models.BooleanField(verbose_name="NIR")
    lack_of_nir_reason = models.CharField(
        max_length=30, verbose_name="raison de l'absence de NIR", blank=True, null=True
    )
    nir_sex = models.CharField(max_length=1, verbose_name="sexe du NIR", blank=True, null=True)
    nir_year = models.CharField(max_length=2, verbose_name="année du NIR", blank=True, null=True)
    birth_year = models.CharField(max_length=4, verbose_name="année de naissance", blank=True, null=True)

    class Meta:
        verbose_name = "Profil de demandeur d'emploi archivé"
        verbose_name_plural = "Profils de demandeurs d'emploi archivés"
        ordering = ["-user__archived_at"]
