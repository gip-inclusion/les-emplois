import datetime

import pytest
from django.urls import reverse_lazy
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from rest_framework.test import APIClient

from itou.api.inbound_parsing.enums import InboundParsingKind
from itou.api.models import BrevoToken
from itou.utils.apis.exceptions import InboundParsingValueError
from itou.utils.apis.inbound_parsing import (
    InboundParsingIdentifier,
    generate_inbound_parsing_address,
    get_inbound_parsing_address,
    parse_inbound_parsing_address,
)
from tests.insertion.factories import MobilizationEmailFactory, ServiceFactory


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
        ({"Recipients": ["random@email.fake"]}, InboundParsingValueError, "Unable to find inbound parsing address"),
    ],
)
def test_get_inbound_parsing_address_exceptions(email, exception, exception_message):
    with pytest.raises(exception, match=exception_message):
        assert get_inbound_parsing_address(email)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("rand0mstring_identifier@domain.fake", InboundParsingIdentifier("rand0mstring", "identifier")),
        ("rand0mstring_identifier+option@domain.fake", InboundParsingIdentifier("rand0mstring", "identifier+option")),
    ],
)
def test_parse_inbound_parsing_email(address, expected):
    assert parse_inbound_parsing_address(address) == expected


@pytest.mark.parametrize(
    "address", ["noseparator@domain.fake", "too_many_separators@domain.fake", "to__many@domain.fake"]
)
def test_parse_inbound_parsing_email_exceptions(address):
    with pytest.raises(InboundParsingValueError, match="Unable to parse inbound parsing address"):
        assert parse_inbound_parsing_address(address)


class TestBrevoInboundParsing:
    WEBHOOK_URL = reverse_lazy("v1:reply-webhook")

    def setup_method(self):
        self.token = BrevoToken.objects.create()
        self.authenticated_client = APIClient(headers={"Authorization": f"Bearer {self.token.key}"})
        self.inbound_parsing_key = "tsnpfnxcraa12q"
        self.inbound_parsing_kind = InboundParsingKind.SERVICE_ANSWER

    def _payload(
        self,
        overrides={},
    ):
        inbound_parsing_address = generate_inbound_parsing_address(
            kind=self.inbound_parsing_kind, key=self.inbound_parsing_key
        )
        return {
            "items": [
                {
                    "From": {"Name": "Brigitte Émettrice", "Address": "brigitte@domain.fake"},
                    "To": [
                        {"Name": "Alain Destinataire", "Address": "alain@otherdomain.fake"},
                        {"Address": inbound_parsing_address},
                    ],
                    "Recipients": [inbound_parsing_address],
                    "Cc": [],
                    "ReplyTo": None,
                    "SentAtDate": "Tue, 1 Sep 2026 09:00:00 +0200",
                    "Subject": "Re: Demande d’orientation",
                    "RawHtmlBody": "<div>Un message</div>",
                    "RawTextBody": "Un message",
                    "ExtractedMarkdownMessage": "Un message",
                    "ExtractedMarkdownSignature": "",
                    "Attachments": [],
                    "Headers": {
                        "Return-Path": "<brigitte@domain.fake>",
                        "Delivered-To": inbound_parsing_address,
                    },
                }
                | overrides
            ]
        }

    def test_inbound_parsing_service_answer(self, snapshot):
        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
            service=ServiceFactory(contact_email="brigitte@domain.fake"),
        )
        assert mobilization_email.answered_at is None

        payload = self._payload()
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at == datetime.datetime(2026, 9, 1, 7, tzinfo=datetime.UTC)

    def test_inbound_parsing_service_answer_event_not_found(self, caplog):
        inbound_parsing_address = generate_inbound_parsing_address(
            kind=self.inbound_parsing_kind, key=self.inbound_parsing_key
        )
        payload = self._payload()
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        assert f"no mobilization_email found for inbound_parsing_address={inbound_parsing_address}" in caplog.messages

    def test_inbound_parsing_service_answer_already_answered(self, caplog):
        inbound_parsing_address = generate_inbound_parsing_address(
            kind=self.inbound_parsing_kind, key=self.inbound_parsing_key
        )
        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
            service=ServiceFactory(contact_email="brigitte@domain.fake"),
            answered_at=datetime.datetime(2026, 1, 1, 15, 30, tzinfo=datetime.UTC),
        )

        now = timezone.now()
        payload = self._payload()
        with freeze_time(now):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at != now

        assert (
            f"mobilization_email={mobilization_email.pk} already got an answer with "
            f"inbound_parsing_address={inbound_parsing_address}" in caplog.messages
        )

    def test_inbound_parsing_service_answer_with_another_contact_email(self, caplog):
        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
            service=ServiceFactory(contact_email="not_brigitte@domain.fake"),
        )

        payload = self._payload()
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at is not None

        assert (
            f"service={mobilization_email.service.uid} replied to mobilization_"
            f"email={mobilization_email.pk} with an address different from contact_email" in caplog.messages
        )

    def test_inbound_parsing_no_kind_match(self, caplog):
        email = "rand0m_nomatch@reply.inclusion.gouv.fr"
        payload = self._payload({"Recipients": [email]})

        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}
        assert f"inbound_parsing_address={email} matched no inbound parsing kind" in caplog.messages

    @pytest.mark.parametrize(
        "sent_at_date,is_now_preferred",
        [
            ("Fri, 16 Oct 2026 15:00:00 +0200 (CEST)", False),
            ("Fri, 16 Oct 2026 15:00:00 +0200 ", False),
            ("wrong date", True),
        ],
    )
    def test_inbound_parsing_date_formats(self, sent_at_date, is_now_preferred):
        email_date = datetime.datetime(2026, 10, 16, 13, tzinfo=datetime.UTC)
        now = datetime.datetime(2026, 10, 16, 13, 5, tzinfo=datetime.UTC)  # a few moments later…

        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
        )
        assert mobilization_email.answered_at is None

        payload = self._payload(overrides={"SentAtDate": sent_at_date})
        with freeze_time(now):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at == now if is_now_preferred else email_date
