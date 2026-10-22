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
    get_parsed_inbound_parsing_address,
)
from tests.insertion.factories import MobilizationEmailFactory, ServiceFactory


@pytest.mark.parametrize(
    "email,expected",
    [
        (
            {"Recipients": ["random@email.fake", "kind.rand0mkey@reply.inclusion.gouv.fr"]},
            InboundParsingIdentifier("kind", "rand0mkey"),
        ),
        (
            {
                "Recipients": ["KiNd.RAND0MKEy+tag@REPLY.inclusion.gouv.fr"],
            },
            InboundParsingIdentifier("kind", "rand0mkey+tag"),
        ),
        (
            {
                "Recipients": [
                    {"Name": "Service", "Address": "kind.rand0mkey@reply.inclusion.gouv.fr"},
                    {"Name": "Pierre DUFOUR", "Address": "random@email.fake"},
                ]
            },
            InboundParsingIdentifier("kind", "rand0mkey"),
        ),
        (
            {"Recipients": ["kind.key1@reply.inclusion.gouv.fr", "kind.key2@reply.inclusion.gouv.fr"]},
            InboundParsingIdentifier("kind", "key1"),
        ),
    ],
    ids=["str_list", "case_insensitive", "mailto_list", "first_match_is_chosen"],
)
def test_parsed_get_inbound_parsing_address(email, expected):
    assert get_parsed_inbound_parsing_address(email) == expected


@pytest.mark.parametrize(
    "email,exception,exception_message",
    [
        ({}, KeyError, "'Recipients'"),
        ({"Recipients": ["random@email.fake"]}, InboundParsingValueError, "Unable to find inbound parsing address"),
        (
            {"Recipients": ["noseparator@reply.inclusion.gouv.fr"]},
            InboundParsingValueError,
            "Unable to parse inbound parsing address",
        ),
        (
            {"Recipients": ["too.many.separators@reply.inclusion.gouv.fr"]},
            InboundParsingValueError,
            "Unable to parse inbound parsing address",
        ),
        (
            {"Recipients": ["too..many@reply.inclusion.gouv.fr"]},
            InboundParsingValueError,
            "Unable to parse inbound parsing address",
        ),
    ],
)
def test_get_parsed_inbound_parsing_address_exceptions(email, exception, exception_message):
    with pytest.raises(exception, match=exception_message):
        assert get_parsed_inbound_parsing_address(email)


class TestBrevoInboundParsing:
    WEBHOOK_URL = reverse_lazy("v1:reply-webhook")

    def setup_method(self):
        self.token = BrevoToken.objects.create()
        self.authenticated_client = APIClient(headers={"Authorization": f"Bearer {self.token.key}"})
        self.inbound_parsing_key = "tsnpfnxcraa12q"
        self.inbound_parsing_kind = InboundParsingKind.SERVICE_ANSWER

    def _payload(self, overrides={}):
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
        now = timezone.now()

        payload = self._payload()
        with assertSnapshotQueries(snapshot(name="SQL queries")), freeze_time(now):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at == now

    def test_inbound_parsing_service_answer_event_not_found(self, caplog):
        payload = self._payload()
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        assert (
            "no mobilization_email found for inbound parsing address "
            f"(kind={self.inbound_parsing_kind}, key={self.inbound_parsing_key})" in caplog.messages
        )

    def test_inbound_parsing_service_answer_already_answered(self, caplog):
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
            f"inbound parsing address (kind={self.inbound_parsing_kind}, key={self.inbound_parsing_key})"
            in caplog.messages
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
        email = "nomatch.rand0m@reply.inclusion.gouv.fr"
        payload = self._payload({"Recipients": [email]})

        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"detail": "Something went wrong, sorry. We've been notified."}
        assert (
            "inbound parsing address (kind=nomatch, key=rand0m) matched no inbound parsing kind" in caplog.messages[0]
        )

    def test_inbound_parsing_dont_process_any_mails_if_exception(self, caplog):
        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
            service=ServiceFactory(contact_email="not_brigitte@domain.fake"),
        )

        payload = self._payload()
        payload["items"].append(
            {
                "From": {"Address": "brigitte@domain.fake"},
                "To": [{"Address": "alain@otherdomain.fake"}],
            },  # Missing a lot of stuff, including Recipients
        )
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"detail": "Something went wrong, sorry. We've been notified."}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at is None  # was not processed
