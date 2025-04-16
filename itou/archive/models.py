import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class ArchivedJobSeeker(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # from User model
    date_joined = models.DateField(verbose_name="année et mois d'inscription")
    first_login = models.DateField(verbose_name="année et mois de première connexion", blank=True, null=True)
    last_login = models.DateField(verbose_name="année et mois de dernière connexion", blank=True, null=True)
    archived_at = models.DateTimeField(auto_now_add=True, verbose_name=_("archived at"))
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

    # from JobSeekerProfile model
    had_pole_emploi_id = models.BooleanField(verbose_name="ID Pôle emploi", default=False)
    had_nir = models.BooleanField(verbose_name="NIR", default=False)
    lack_of_nir_reason = models.CharField(verbose_name="raison de l'absence de NIR", blank=True, null=True)
    nir_sex = models.PositiveSmallIntegerField(verbose_name="sexe du NIR", blank=True, null=True)
    nir_year = models.PositiveSmallIntegerField(verbose_name="année du NIR", blank=True, null=True)
    birth_year = models.PositiveSmallIntegerField(verbose_name="année de naissance", blank=True, null=True)

    class Meta:
        verbose_name = "candidat archivé"
        verbose_name_plural = "candidats archivés"
        ordering = ["-archived_at"]
