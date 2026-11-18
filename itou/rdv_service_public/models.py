import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone
from encrypted_fields import EncryptedCharField


class OAuthToken(models.Model):
    """The token that lets Les Emplois call RDV Service Public on behalf of a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="rdv_service_public_oauth_token",
    )
    access_token = EncryptedCharField(verbose_name="jeton d'accès")
    refresh_token = EncryptedCharField(verbose_name="jeton de rafraîchissement")
    expires_at = models.DateTimeField(verbose_name="date d'expiration du jeton d'accès")
    rdv_service_public_agent_id = models.IntegerField(verbose_name="identifiant de l'agent RDV-S")
    created_at = models.DateTimeField(verbose_name="date de création", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "jeton OAuth RDV Service Public"
        verbose_name_plural = "jetons OAuth RDV Service Public"

    @classmethod
    def save_for_user(cls, user, token_data, *, agent_id):
        cls.objects.update_or_create(
            user=user,
            defaults={
                "access_token": token_data.access_token,
                "refresh_token": token_data.refresh_token,
                "expires_at": timezone.now() + datetime.timedelta(seconds=token_data.expires_in),
                "rdv_service_public_agent_id": agent_id,
            },
        )
