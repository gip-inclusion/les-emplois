import datetime

import pytest
from django.conf import settings
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
from itou.utils.brand import product_name
from tests.insertion.factories import MobilizationEmailFactory, ServiceFactory


@pytest.mark.parametrize(
    "email,expected",
    [
        (
            {"Recipients": ["random@email.fake", "kind.rand0mkey@reply.inclusion.test.fr"]},
            InboundParsingIdentifier("kind", "rand0mkey"),
        ),
        (
            {
                "Recipients": ["KiNd.RAND0MKEy+tag@REPLY.inclusion.test.fr"],
            },
            InboundParsingIdentifier("kind", "rand0mkey+tag"),
        ),
        (
            {
                "Recipients": [
                    {"Name": "Service", "Address": "kind.rand0mkey@reply.inclusion.test.fr"},
                    {"Name": "Pierre DUFOUR", "Address": "random@email.fake"},
                ]
            },
            InboundParsingIdentifier("kind", "rand0mkey"),
        ),
        (
            {"Recipients": ["kind.key1@reply.inclusion.test.fr", "kind.key2@reply.inclusion.test.fr"]},
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
            {"Recipients": ["noseparator@reply.inclusion.test.fr"]},
            InboundParsingValueError,
            "Unable to parse inbound parsing address",
        ),
        (
            {"Recipients": ["too.many.separators@reply.inclusion.test.fr"]},
            InboundParsingValueError,
            "Unable to parse inbound parsing address",
        ),
        (
            {"Recipients": ["too..many@reply.inclusion.test.fr"]},
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
                    "RawHtmlBody": "<div>Bonjour,<br>Un message.</div>",
                    "RawTextBody": "Bonjour,\nUn message.",
                    "ExtractedMarkdownMessage": "Bonjour,\nUn message.",
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

    def test_inbound_parsing_service_answer(
        self, snapshot, django_capture_on_commit_callbacks, settings, mailoutbox, caplog
    ):
        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
            service=ServiceFactory(contact_email="brigitte@domain.fake"),
        )
        assert mobilization_email.answered_at is None
        now = timezone.now()

        payload = self._payload()
        email_in_payload = payload["items"][0]
        with (
            assertSnapshotQueries(snapshot(name="SQL queries")),
            freeze_time(now),
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at == now

        [email_to_sender] = mailoutbox
        assert email_to_sender.to == [mobilization_email.sender.email]
        assert (
            email_to_sender.from_email
            == f"{email_in_payload['From']['Name']} {product_name('via')} <{settings.DEFAULT_FROM_EMAIL}>"
        )
        # The email’s From address is filled in `reply_to`, not the service’s contact_email
        assert email_to_sender.reply_to == [
            f"{email_in_payload['From']['Name']} <{email_in_payload['From']['Address']}>"
        ]
        assert "Bonjour,\nUn message." in email_to_sender.body

        assert (
            f"forwarded email from service={mobilization_email.service.uid} in reply to "
            f"mobilization_email={mobilization_email.pk}" in caplog.messages
        )

    def test_inbound_parsing_service_answer_event_not_found(self, caplog):
        payload = self._payload()
        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        assert (
            "no mobilization_email found for inbound parsing address "
            f"(kind={self.inbound_parsing_kind}, key={self.inbound_parsing_key})" in caplog.messages
        )

    def test_inbound_parsing_service_answer_already_answered(
        self, caplog, django_capture_on_commit_callbacks, mailoutbox
    ):
        mobilization_email = MobilizationEmailFactory(
            inbound_parsing_key=self.inbound_parsing_key,
            service=ServiceFactory(contact_email="brigitte@domain.fake"),
            answered_at=datetime.datetime(2026, 1, 1, 15, 30, tzinfo=datetime.UTC),
        )

        now = timezone.now()
        payload = self._payload()
        with freeze_time(now), django_capture_on_commit_callbacks(execute=True):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at != now

        assert (
            f"mobilization_email={mobilization_email.pk} already got an answer with "
            f"inbound parsing address (kind={self.inbound_parsing_kind}, key={self.inbound_parsing_key})"
            in caplog.messages
        )

        # The email is forwarded
        assert len(mailoutbox) == 1

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

    @pytest.mark.parametrize(
        "from_email, forwarded_from, forwarded_reply_to",
        [
            (
                {"Name": "Jane DOE", "Address": "jane@domain.fake"},
                f"Jane DOE via La plateforme de l’inclusion <{settings.DEFAULT_FROM_EMAIL}>",
                "Jane DOE <jane@domain.fake>",
            ),
            ({"Name": "", "Address": "jane@domain.fake"}, settings.DEFAULT_FROM_EMAIL, "jane@domain.fake"),
            ({"Address": "jane@domain.fake"}, settings.DEFAULT_FROM_EMAIL, "jane@domain.fake"),
        ],
    )
    def test_inbound_parsing_service_answer_email_names(
        self, from_email, forwarded_from, forwarded_reply_to, django_capture_on_commit_callbacks, mailoutbox
    ):
        MobilizationEmailFactory(inbound_parsing_key=self.inbound_parsing_key)
        payload = self._payload({"From": from_email})
        with django_capture_on_commit_callbacks(execute=True):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        [email_to_sender] = mailoutbox
        assert email_to_sender.from_email == forwarded_from
        assert email_to_sender.reply_to == [forwarded_reply_to]

    def test_inbound_parsing_no_kind_match(self, caplog):
        email = "nomatch.rand0m@reply.inclusion.test.fr"
        payload = self._payload({"Recipients": [email]})

        response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"detail": "Something went wrong, sorry. We've been notified."}
        assert (
            "inbound parsing address (kind=nomatch, key=rand0m) matched no inbound parsing kind" in caplog.messages[0]
        )

    @pytest.mark.parametrize(
        "attachment_payload",
        [
            {
                "Name": "cv.pdf",
                "ContentType": "application/pdf",
                "ContentLength": 1024,
                "ContentID": "someId",
                "DownloadToken": "t0k3n",
            },
            {},
            {
                "Name": "cv.pdf",
                "SomethingElse": 1,
            },
        ],
    )
    def test_inbound_parsing_service_answer_with_attachments(
        self, django_capture_on_commit_callbacks, mailoutbox, attachment_payload
    ):
        mobilization_email = MobilizationEmailFactory(inbound_parsing_key=self.inbound_parsing_key)

        payload = self._payload({"Attachments": [attachment_payload]})
        with django_capture_on_commit_callbacks(execute=True):
            response = self.authenticated_client.post(self.WEBHOOK_URL, payload, format="json")
        assert response.json() == {"msg": "ok"}

        mobilization_email.refresh_from_db()
        assert mobilization_email.answered_at is not None

        # The email is forwarded
        assert len(mailoutbox) == 1

    def test_inbound_parsing_dont_process_any_mails_if_exception(self):
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
