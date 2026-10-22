import dataclasses
import datetime
import logging
import uuid

from django.conf import settings
from django.db import models

from itou.rdv_insertion.enums import (
    RSA_MOTIF_CATEGORY_TYPES,
    AppointmentCreatedBy,
    AppointmentLocationType,
    InvitationRequestReasonCategory,
    InvitationStatus,
    InvitationType,
    MotifCategoryType,
    ParticipationStatus,
)


logger = logging.getLogger(__name__)


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
    rdv_insertion_user_id = models.IntegerField(db_index=True, editable=False)
    rdv_insertion_id = models.IntegerField(unique=True, null=True, editable=False)

    class Meta:
        verbose_name = "participation à un événement RDV-I"
        verbose_name_plural = "participations aux événements RDV-I"


class Location(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField("nom", editable=False)
    address = models.CharField("adresse", editable=False)
    phone_number = models.CharField("téléphone", null=True, editable=False)
    rdv_solidarites_id = models.IntegerField(unique=True, editable=False)

    class Meta:
        verbose_name = "lieu d'un événement RDV-I"
        verbose_name_plural = "lieux d'événements RDV-I"


class WebhookEvent(models.Model):
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    body = models.JSONField(editable=False)
    headers = models.JSONField(editable=False)
    is_processed = models.BooleanField(default=False, editable=False)

    class Meta:
        verbose_name = "événement du webhook RDV-I"
        verbose_name_plural = "événements du webhook RDV-I"
        indexes = [
            models.Index(models.F("body__data__id"), name="webhookevent_rdvi_id_idx"),
            models.Index(models.F("body__meta__model"), name="webhookevent_rdvi_type_idx"),
        ]

    @property
    def for_appointment(self):
        return self.body["meta"]["model"].lower() == "rdv"

    @property
    def for_invitation(self):
        return self.body["meta"]["model"].lower() == "invitation"


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class AppointmentAgentData:
    first_name: str | None
    last_name: str | None
    email: str

    def get_full_name(self):
        full_name = f"{(self.first_name or '').strip().title()} {(self.last_name or '').upper()}"
        return full_name.strip()


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class JobSeekerAppointmentData:
    """A job seeker's appointment, from rdv-insertion's API or the invitation experiment. Not stored."""

    rdv_insertion_id: int
    status: ParticipationStatus
    start_at: datetime.datetime
    theme: str
    reason: str
    organization_name: str
    location_type: AppointmentLocationType | None
    location_name: str | None
    address: str | None
    agents: tuple[AppointmentAgentData, ...]
    created_by: AppointmentCreatedBy | None

    @classmethod
    def from_api(cls, participation, *, theme):
        rdv = participation["rdv"]
        lieu = rdv["lieu"]
        return cls(
            rdv_insertion_id=rdv["id"],
            status=ParticipationStatus(participation["status"]),
            start_at=datetime.datetime.fromisoformat(participation["starts_at"]),
            theme=theme,
            reason=rdv["motif"]["name"],
            organization_name=rdv["organisation"]["name"],
            location_type=AppointmentLocationType(rdv["motif"]["location_type"]),
            location_name=lieu["name"] if lieu else None,
            address=lieu["address"] if lieu else rdv["address"],
            agents=tuple(
                AppointmentAgentData(
                    first_name=agent["first_name"], last_name=agent["last_name"], email=agent["email"]
                )
                for agent in rdv["agents"]
            ),
            created_by=AppointmentCreatedBy(participation["created_by"]),
        )

    @classmethod
    def list_from_api(cls, follow_ups):
        """Appointments of the RSA follow-ups returned by rdv-insertion's API."""
        try:
            return [
                cls.from_api(
                    participation, theme=MotifCategoryType(follow_up["motif_category"]["motif_category_type"]).label
                )
                for follow_up in follow_ups
                # SIAE appointments are only shown when stored by the invitation experiment,
                # the only source that links them to their company
                if follow_up["motif_category"]["motif_category_type"] in RSA_MOTIF_CATEGORY_TYPES
                for participation in follow_up["participations"]
            ]
        except KeyError, TypeError, ValueError:
            logger.exception("Unexpected rdv-insertion data")
            return []

    @classmethod
    def from_stored_participation(cls, participation):
        appointment = participation.appointment
        location = appointment.location
        return cls(
            rdv_insertion_id=appointment.rdv_insertion_id,
            status=ParticipationStatus(participation.status),
            start_at=appointment.start_at,
            theme="Suite à une candidature",
            reason=appointment.reason,
            organization_name=appointment.company.display_name,
            location_name=location.name if location else None,
            address=location.address if location else appointment.address,
            # Not stored by the invitation experiment
            location_type=None,
            agents=(),
            created_by=None,
        )
