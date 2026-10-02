import datetime

import pytest
from django.urls import reverse_lazy
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from rest_framework.test import APIClient

from itou.api.inbound_parsing.views import get_inbound_parsing_address, parse_inbound_parsing_address
from itou.api.models import BrevoToken
from itou.insertion.enums import MobilizationEventKind
from tests.insertion.factories import MobilizationEventFactory, ServiceFactory


@pytest.mark.parametrize(
    "email,expected",
    [
        (
            {"Recipients": ["random@email.fake", "recipient@reply.inclusion.gouv.fr"]},
            "recipient@reply.inclusion.gouv.fr",
        ),
        ({"Recipients": ["RecipiEnT@REPLY.inclusion.gouv.fr"]}, "recipient@reply.inclusion.gouv.fr"),
        (
            {
                "Recipients": [
                    {"Name": "Service", "Address": "recipient@reply.inclusion.gouv.fr"},
                    {"Name": "Pierre DUFOUR", "Address": "random@email.fake"},
                ]
            },
            "recipient@reply.inclusion.gouv.fr",
        ),
        (
            {"Recipients": ["recipient1@reply.inclusion.gouv.fr", "recipient2@reply.inclusion.gouv.fr"]},
            "recipient1@reply.inclusion.gouv.fr",
        ),
    ],
    ids=["str_list", "case_insensitive", "mailto_list", "first_match_is_taken"],
)
def test_get_inbound_parsing_address(email, expected):
    assert get_inbound_parsing_address(email) == expected


@pytest.mark.parametrize(
    "email,exception,exception_message",
    [
        ({}, KeyError, "'Recipients'"),
        ({"Recipients": ["random@email.fake"]}, ValueError, "Unable to find inbound parsing address"),
    ],
)
def test_get_inbound_parsing_address_exceptions(email, exception, exception_message):
    with pytest.raises(exception, match=exception_message):
        assert get_inbound_parsing_address(email)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("kind.identifier@domain.fake", ["kind", "identifier"]),
        ("kind.identifier+option@domain.fake", ["kind", "identifier+option"]),
    ],
)
def test_parse_inbound_parsing_email(address, expected):
    assert parse_inbound_parsing_address(address) == expected


@pytest.mark.parametrize(
    "address", ["noseparator@domain.fake", "to.many.separators@domain.fake", "to..many@domain.fake"]
)
def test_parse_inbound_parsing_email_exceptions(address):
    with pytest.raises(ValueError, match="Unable to parse inbound parsing address"):
        assert parse_inbound_parsing_address(address)


class TestBrevoInboundParsing:
    WEBHOOK_URL = reverse_lazy("v1:reply-webhook")

    def setup_method(self):
        self.token = BrevoToken.objects.create()
        self.authenticated_client = APIClient(headers={"Authorization": f"Token {self.token.key}"})

    def _payload(self, overrides={}):
        return {
            "items": [
                {
                    "Uuid": ["1a825d56-029b-4a41-b8e4-61670463431b"],
                    "MessageId": "<CAN0zNmMsj_xOx8hCREv3rbovcYE3m5rZh8eRe+QSKC0yff_W6A@domain.fake>",
                    "InReplyTo": "<e6df8cf2-cfb2-2cb6-320f-d9cba05a3001@otherdomain.fake>",
                    "From": {"Name": "Brigitte Émettrice", "Address": "brigitte@domain.fake"},
                    "To": [
                        {"Name": "Alain Destinataire", "Address": "alain@otherdomain.fake"},
                        {"Address": "service.tsnpfnxcra@reply.inclusion.gouv.fr"},
                    ],
                    "Recipients": ["service.tsnpfnxcra@reply.inclusion.gouv.fr"],
                    "Cc": [],
                    "ReplyTo": None,
                    "SentAtDate": "Tue, 1 Sep 2026 09:53:21 +0200",
                    "Subject": "Re: Demande d’orientation",
                    "RawHtmlBody": "<div>Un message</div>",
                    "RawTextBody": "Un message",
                    "ExtractedMarkdownMessage": "Un message",
                    "ExtractedMarkdownSignature": "",
                    "SpamScore": 3.3,
                    "Attachments": [],
                    "Headers": {
                        "Return-Path": "<brigitte@domain.fake>",
                        "Delivered-To": "service.tSnpfNXCra@reply.inclusion.gouv.fr",
                    },
                }
                | overrides
            ]
        }

    def test_inbound_parsing_service_answer(self, snapshot):
        inbound_key = "tsnpfnxcra"
        mobilization_event = MobilizationEventFactory(
            kind=MobilizationEventKind.SEND_EMAIL_TO_SERVICE,
            service=ServiceFactory(contact_email="brigitte@domain.fake"),
            inbound_key=inbound_key,
        )
        assert mobilization_event.service_answered_at is None

        now = timezone.now()
        payload = self._payload({"Recipients": [f"service.{inbound_key}@reply.inclusion.gouv.fr"]})
        with freeze_time(now):
            with assertSnapshotQueries(snapshot(name="SQL queries")):
                response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_event.refresh_from_db()
        assert mobilization_event.service_answered_at == now

    def test_inbound_parsing_service_answer_event_not_found(self, caplog):
        payload = self._payload({"Recipients": ["service.somethingelse@reply.inclusion.gouv.fr"]})
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        assert (
            "no mobilization_event found for inbound_parsing_address=service.somethingelse@reply.inclusion.gouv.fr"
            in caplog.messages
        )

    def test_inbound_parsing_service_answer_already_answered(self, caplog):
        inbound_key = "tsnpfnxcra"
        mobilization_event = MobilizationEventFactory(
            kind=MobilizationEventKind.SEND_EMAIL_TO_SERVICE,
            service=ServiceFactory(contact_email="brigitte@domain.fake"),
            inbound_key=inbound_key,
            service_answered_at=datetime.datetime(2026, 1, 1, 15, 30, tzinfo=datetime.UTC),
        )

        now = timezone.now()
        payload = self._payload({"Recipients": [f"service.{inbound_key}@reply.inclusion.gouv.fr"]})
        with freeze_time(now):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_event.refresh_from_db()
        assert mobilization_event.service_answered_at != now

        assert (
            f"mobilization_event={mobilization_event.pk} already got an answer with "
            f"inbound_parsing_address=service.{inbound_key}@reply.inclusion.gouv.fr" in caplog.messages
        )

    def test_inbound_parsing_service_answer_with_another_contact_email(self, caplog):
        inbound_key = "tsnpfnxcra"
        mobilization_event = MobilizationEventFactory(
            kind=MobilizationEventKind.SEND_EMAIL_TO_SERVICE,
            service=ServiceFactory(contact_email="not_brigitte@not_domain.fake"),
            inbound_key=inbound_key,
        )

        payload = self._payload({"Recipients": [f"service.{inbound_key}@reply.inclusion.gouv.fr"]})
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_event.refresh_from_db()
        assert mobilization_event.service_answered_at is not None

        assert (
            f"service={mobilization_event.service.uid} replied to mobilization_"
            f"event={mobilization_event.pk} with an address different from contact_email" in caplog.messages
        )

    @pytest.mark.parametrize(
        "email", ["unrecognized@reply.inclusion.gouv.fr", "something.else@reply.inclusion.gouv.fr"]
    )
    def test_inbound_parsing_no_kind_match(self, email, caplog):
        payload = self._payload({"Recipients": [email]})
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        assert f"inbound_parsing_address={email} matched no inbound parsing kind" in caplog.messages
