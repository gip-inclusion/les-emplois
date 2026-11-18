import datetime
import uuid

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from encrypted_fields import EncryptedCharField

from itou.utils.apis.rdv_service_public import RdvServicePublicInvalidTokenError, get_oauth_client


# Refresh a little before the expiry, so that the token stays valid during the calls that follow
REFRESH_TOKEN_MARGIN = datetime.timedelta(minutes=1)


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

    @property
    def needs_refresh(self):
        return self.expires_at <= timezone.now() + REFRESH_TOKEN_MARGIN

    def refresh_access_token(self):
        """Exchange the refresh token for a new access token, unless a concurrent request already did.

        Raises RdvServicePublicInvalidTokenError if RDV Service Public refuses the refresh token,
        and RdvServicePublicApiError if it can't be reached.
        """
        # RDV Service Public revokes the previous refresh token as soon as the new access token is used:
        # the new token must be committed even if the request fails afterwards.
        # durable=True raises an error if this block is nested in a transaction, which would delay the commit.
        with transaction.atomic(durable=True):
            try:
                # Wait for a concurrent refresh to end, then read its result
                self.refresh_from_db(from_queryset=OAuthToken.objects.select_for_update())
            except OAuthToken.DoesNotExist:
                # Deleted by a concurrent request: like a refused token, the user must link their account again
                raise RdvServicePublicInvalidTokenError("The token was deleted by a concurrent request")
            if not self.needs_refresh:
                return
            token_data = get_oauth_client().refresh_token(self.refresh_token)
            self.access_token = token_data.access_token
            self.refresh_token = token_data.refresh_token
            self.expires_at = timezone.now() + datetime.timedelta(seconds=token_data.expires_in)
            self.save()


class AppointmentProposal(models.Model):
    """A click on "Proposer un RDV": the rdv_plan created in RDV Service Public for the job seeker."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_application = models.ForeignKey(
        "job_applications.JobApplication",
        verbose_name="candidature",
        on_delete=models.CASCADE,
        related_name="rdv_service_public_proposals",
    )
    # Company and job seeker at the time of the click: the job application can be transferred afterwards
    company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise",
        on_delete=models.CASCADE,
        related_name="rdv_service_public_proposals",
    )
    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="rdv_service_public_proposals",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créée par",
        on_delete=models.RESTRICT,
        related_name="+",
    )
    created_at = models.DateTimeField(verbose_name="créée le", auto_now_add=True)
    rdv_service_public_plan_id = models.IntegerField(verbose_name="identifiant du plan RDV-S", unique=True)
    rdv_service_public_user_id = models.IntegerField(
        verbose_name="identifiant de la fiche usager RDV-S", db_index=True
    )

    class Meta:
        verbose_name = "proposition de RDV"
        verbose_name_plural = "propositions de RDV"
