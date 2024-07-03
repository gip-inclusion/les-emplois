import uuid

from django.conf import settings
from django.db import models

from .enums import InvitationStatus, InvitationType


class InvitationRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="rdvi_invitation_requests",
    )
    company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise",
        on_delete=models.CASCADE,
        related_name="rdvi_invitation_requests",
    )

    created_at = models.DateTimeField("créée le", auto_now_add=True)
    api_response = models.JSONField(editable=False)
    rdv_insertion_user_id = models.IntegerField(db_index=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "demande d'invitation RDV-I"
        verbose_name_plural = "demandes d'invitation RDV-I"


class Invitation(models.Model):
    Type = InvitationType
    Status = InvitationStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField("format", choices=Type.choices)
    status = models.CharField("état", default=Status.SENT, choices=InvitationStatus.choices)
    invitation_request = models.ForeignKey(
        "InvitationRequest",
        verbose_name="demande d'invitation",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    rdv_insertion_invitation_id = models.IntegerField(unique=True, editable=False)

    class Meta:
        verbose_name = "invitation RDV-I"
        verbose_name_plural = "invitations RDV-I"
        constraints = [
            models.UniqueConstraint(
                name="unique_%(class)s_type_per_invitation_request",
                fields=["type", "invitation_request"],
                violation_error_message="Une invitation de ce type existe déjà pour cette demande",
            )
        ]
