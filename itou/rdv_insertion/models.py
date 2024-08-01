import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import InvitationRequestReasonCategory, InvitationStatus, InvitationType, ParticipationStatus


class InvitationRequest(models.Model):
    ReasonCategory = InvitationRequestReasonCategory

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
    reason_category = models.CharField("catégorie de motif", choices=ReasonCategory.choices)

    created_at = models.DateTimeField("créée le", auto_now_add=True)
    api_response = models.JSONField(editable=False)
    rdv_insertion_user_id = models.IntegerField(db_index=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "demande d'invitation RDV-I"
        verbose_name_plural = "demandes d'invitation RDV-I"

    @property
    def email_invitation(self):
        return next((invit for invit in self.invitations.all() if invit.is_email), None)

    @property
    def sms_invitation(self):
        return next((invit for invit in self.invitations.all() if invit.is_sms), None)


class Invitation(models.Model):
    Type = InvitationType
    Status = InvitationStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField("format", choices=Type.choices)
    status = models.CharField("état", default=Status.SENT, choices=Status.choices)
    delivered_at = models.DateTimeField("délivrée le", null=True, editable=False)
    invitation_request = models.ForeignKey(
        "InvitationRequest",
        verbose_name="demande d'invitation",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    rdv_insertion_id = models.IntegerField(unique=True, editable=False)

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

    @property
    def is_email(self):
        return self.type == self.Type.EMAIL

    @property
    def is_postal(self):
        return self.type == self.Type.POSTAL

    @property
    def is_sms(self):
        return self.type == self.Type.SMS


class Appointment(models.Model):
    Status = ParticipationStatus
    ReasonCategory = InvitationRequestReasonCategory

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise",
        on_delete=models.CASCADE,
        related_name="rdvi_appointments",
        editable=False,
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="participants",
        related_name="rdvi_appointments",
        through="Participation",
        editable=False,
    )
    location = models.ForeignKey(
        "Location",
        null=True,
        verbose_name="lieu",
        on_delete=models.SET_NULL,
        related_name="rdvi_appointments",
        editable=False,
    )

    status = models.CharField("état", default=Status.UNKNOWN, choices=Status.choices, editable=False)
    reason_category = models.CharField("catégorie de motif", choices=ReasonCategory.choices, editable=False)
    reason = models.CharField("motif", editable=False)
    is_collective = models.BooleanField("rendez-vous collectif", editable=False)
    start_at = models.DateTimeField("commence le", editable=False)
    duration = models.DurationField("durée", editable=False)
    canceled_at = models.DateTimeField("annulé le", null=True, editable=False)
    address = models.CharField("adresse", editable=False)
    total_participants = models.PositiveSmallIntegerField("nombre de participants", null=True, editable=False)
    max_participants = models.PositiveSmallIntegerField("nombre max. de participants", null=True, editable=False)
    rdv_insertion_id = models.IntegerField(unique=True, editable=False)

    class Meta:
        verbose_name = "rendez-vous RDV-I"
        verbose_name_plural = "rendez-vous RDV-I"


class Participation(models.Model):
    Status = ParticipationStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="rdvi_participations",
        editable=False,
    )
    appointment = models.ForeignKey(
        "Appointment",
        verbose_name="rendez-vous",
        on_delete=models.CASCADE,
        related_name="rdvi_participations",
        editable=False,
    )
    status = models.CharField("état", default=Status.UNKNOWN, choices=Status.choices, editable=False)
    rdv_insertion_id = models.IntegerField(unique=True, editable=False)

    class Meta:
        verbose_name = "participation à un événement RDV-I"
        verbose_name_plural = "participations aux événements RDV-I"

    def get_status_display(self):
        if self.status == self.Status.UNKNOWN:
            if self.appointment.start_at > timezone.now():
                return "RDV à venir"
            return "Statut du RDV à préciser"
        return self._get_FIELD_display(field=self._meta.get_field("status"))

    def get_status_class_name(self):
        return {
            self.Status.UNKNOWN: "bg-important-lightest text-important",
            self.Status.SEEN: "bg-success-lighter text-success",
            self.Status.REVOKED: "bg-warning-lighter text-warning",
            self.Status.EXCUSED: "bg-warning-lighter text-warning",
            self.Status.NOSHOW: "bg-danger-lighter text-danger",
        }.get(self.status)


class Location(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField("nom", editable=False)
    address = models.CharField("adresse", editable=False)
    phone_number = models.CharField("téléphone", null=True, editable=False)
    rdv_insertion_id = models.IntegerField(unique=True, editable=False)

    class Meta:
        verbose_name = "lieu d'un événement RDV-I"
        verbose_name_plural = "lieux d'événements RDV-I"


class WebhookEvent(models.Model):
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    body = models.JSONField(editable=False)
    headers = models.JSONField(editable=False)

    class Meta:
        verbose_name = "événement du webhook RDV-I"
        verbose_name_plural = "événements du webhook RDV-I"
