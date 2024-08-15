import datetime
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from itou.rdv_insertion.models import Appointment, Invitation, Location, Participation, WebhookEvent
from itou.utils.mocks import rdv_insertion as rdv_insertion_mocks
from itou.www.rdv_insertion.views import InvalidSignature, SignatureMissing, UnsupportedEvent
from tests.rdv_insertion.factories import InvitationRequestFactory


class TestRdvInsertion:
    @classmethod
    def _make_rdvi_signature(cls, raw_data):
        return hmac.new(settings.RDV_INSERTION_WEBHOOK_SECRET.encode(), raw_data, hashlib.sha256).hexdigest()

    def test_webhook_handler_signature_missing(self, client, caplog):
        caplog.set_level(logging.INFO, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        response = client.post(url, json=rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY)
        assert response.status_code == 401
        assert caplog.messages[0] == "Payload encoding is UTF-8"
        assert caplog.messages[1] == "Error while handling RDVI webhook"
        assert caplog.records[1].exc_info[0] == SignatureMissing

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_signature_invalid(self, client, caplog):
        caplog.set_level(logging.INFO, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        response = client.post(
            url,
            json=rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY,
            headers={"x-rdvi-signature": "invalid"},
        )
        assert response.status_code == 401
        assert caplog.messages[0] == "Payload encoding is UTF-8"
        assert caplog.messages[1] == "Error while handling RDVI webhook"
        assert caplog.records[1].exc_info[0] == InvalidSignature

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_signature_valid_with_utf8(self, client, caplog):
        """
        Test that a signed utf8 payload sent encoded with utf8 is valid.
        (RDVI behavior with appointment events)
        """
        caplog.set_level(logging.INFO, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY, ensure_ascii=False).encode()
        response = client.post(
            url,
            data=raw_data,
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 200
        assert caplog.messages[0] == "Payload encoding is UTF-8"

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_signature_valid_with_latin1(self, client, caplog):
        """
        Test that a signed utf-8 payload sent encoded with utf-8 is valid.
        (RDVI behavior with invitation events)
        """
        caplog.set_level(logging.INFO, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY, ensure_ascii=False).encode()
        response = client.post(
            url,
            data=raw_data.decode().encode("latin-1"),
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 200
        assert caplog.messages[0] == "Payload encoding is LATIN-1"

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_logs_invalid_events(self, client, caplog):
        caplog.set_level(logging.WARNING, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(
            {
                "data": {},
                "meta": {"event": "updated", "model": "Invalid", "timestamp": "2024-08-15 19:23:12 +0200"},
            },
            ensure_ascii=False,
        ).encode()
        response = client.post(
            url,
            data=raw_data.decode().encode("latin-1"),
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 400
        assert caplog.messages[0] == "Error while handling RDVI webhook"
        assert caplog.records[0].exc_info[0] == UnsupportedEvent

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_does_not_update_invitation(self, client, caplog):
        """
        Should ignore events with no invitation requests matching organization + job seeker
        """
        caplog.set_level(logging.INFO, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY, ensure_ascii=False).encode()
        response = client.post(
            url,
            data=raw_data,
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 200
        assert caplog.messages[0] == "Payload encoding is UTF-8"
        assert caplog.messages[1] == "No invitations matching rdv_insertion_id={}".format(
            rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY["data"]["id"]
        )

        # Event must be persisted as-is, unprocessed
        webhook_event = WebhookEvent.objects.get()
        assert webhook_event.body == rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY
        assert not webhook_event.is_processed

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_updates_invitation(self, client):
        body_data = rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY["data"]

        invitation_request = InvitationRequestFactory(
            company__rdv_solidarites_id=1234,
            rdv_insertion_user_id=body_data["user"]["id"],
            email_invitation__status=Invitation.Status.SENT,
            email_invitation__rdv_insertion_id=body_data["id"],
        )

        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY, ensure_ascii=False).encode()
        response = client.post(
            url,
            data=raw_data,
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 200

        # Event must be persisted as-is, flagged processed
        webhook_event = WebhookEvent.objects.get()
        assert webhook_event.body == rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY
        assert webhook_event.is_processed

        # Check for updated objects
        assert invitation_request.email_invitation.status == Invitation.Status.OPENED
        assert invitation_request.email_invitation.delivered_at == datetime.datetime.fromisoformat(
            rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY["data"]["delivered_at"]
        )

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_does_not_create_appointment(self, client, caplog):
        """
        Should ignore events with no invitation requests matching organization + job seeker
        """
        caplog.set_level(logging.INFO, logger="itou.rdv_insertion")
        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY, ensure_ascii=False).encode()
        response = client.post(
            url,
            data=raw_data,
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 200
        assert caplog.messages[0] == "Payload encoding is UTF-8"
        assert caplog.messages[1] == "No invitation requests matching rdvs_company_id={}, rdvi_user_ids=[{}]".format(
            rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY["data"]["organisation"][
                "rdv_solidarites_organisation_id"
            ],
            rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY["data"]["users"][0]["id"],
        )

        # Event must be persisted as-is, unprocessed
        webhook_event = WebhookEvent.objects.get()
        assert webhook_event.body == rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY
        assert not webhook_event.is_processed

        # No other objects should be created
        assert not Location.objects.exists()
        assert not Appointment.objects.exists()
        assert not Participation.objects.exists()

    @override_settings(RDV_INSERTION_WEBHOOK_SECRET="much-much-secret")
    def test_webhook_handler_creates_appointment(self, client):
        body_data = rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY["data"]

        invitation_request = InvitationRequestFactory(
            company__rdv_solidarites_id=body_data["organisation"]["rdv_solidarites_organisation_id"],
            rdv_insertion_user_id=body_data["users"][0]["id"],
        )

        url = reverse("rdv_insertion:webhook")
        raw_data = json.dumps(rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY, ensure_ascii=False).encode()
        response = client.post(
            url,
            data=raw_data,
            content_type="application/json",
            headers={"x-rdvi-signature": self._make_rdvi_signature(raw_data)},
        )
        assert response.status_code == 200

        # Event must be persisted as-is, flagged processed
        webhook_event = WebhookEvent.objects.get()
        assert webhook_event.body == rdv_insertion_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY
        assert webhook_event.is_processed

        # Check for created objects
        appointment = Appointment.objects.select_related("location").get()
        assert appointment.company == invitation_request.company
        assert appointment.status == appointment.Status.UNKNOWN
        assert appointment.reason_category == appointment.ReasonCategory.SIAE_INTERVIEW
        assert appointment.reason == body_data["motif"]["name"]
        assert appointment.is_collective == body_data["motif"]["collectif"]
        assert appointment.start_at == datetime.datetime.fromisoformat(body_data["starts_at"])
        assert appointment.duration == datetime.timedelta(minutes=body_data["duration_in_min"])
        assert appointment.canceled_at == datetime.datetime.fromisoformat(body_data["cancelled_at"])
        assert appointment.address == body_data["lieu"]["address"]
        assert appointment.total_participants == body_data["users_count"]
        assert appointment.max_participants == body_data["max_participants_count"]
        assert appointment.rdv_insertion_id == body_data["id"]

        participation = appointment.rdvi_participations.get()
        assert participation.job_seeker == invitation_request.job_seeker
        assert participation.status == participation.Status.UNKNOWN
        assert participation.rdv_insertion_user_id == body_data["participations"][0]["user"]["id"]
        assert participation.rdv_insertion_id == body_data["participations"][0]["id"]

        assert appointment.location.name == body_data["lieu"]["name"]
        assert appointment.location.address == body_data["lieu"]["address"]
        assert appointment.location.phone_number == body_data["lieu"]["phone_number"]
        assert appointment.location.rdv_solidarites_id == body_data["lieu"]["rdv_solidarites_lieu_id"]
