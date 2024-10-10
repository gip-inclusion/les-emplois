import datetime
from urllib.parse import urljoin

import httpx
import pytest
import respx
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from freezegun import freeze_time

from itou.rdv_insertion.api import (
    RDV_I_INVITATION_DELIVERED_STATUSES,
    RDV_I_INVITATION_NOT_DELIVERED_STATUSES,
    RDV_S_CREDENTIALS_CACHE_KEY,
    get_api_credentials,
    get_invitation_status,
)
from itou.rdv_insertion.models import Invitation, Participation
from itou.utils.mocks.rdv_insertion import (
    RDV_INSERTION_AUTH_FAILURE_BODY,
    RDV_INSERTION_AUTH_SUCCESS_BODY,
    RDV_INSERTION_AUTH_SUCCESS_HEADERS,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.rdv_insertion.factories import (
    InvitationFactory,
    InvitationRequestFactory,
    ParticipationFactory,
    WebhookEventFactory,
)


class TestRDVInsertionTokenRenewal:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.RDV_SOLIDARITES_API_BASE_URL = "https://rdv-solidarites.fake/api/v1/"
        settings.RDV_SOLIDARITES_EMAIL = "tech@inclusion.beta.gouv.fr"
        settings.RDV_SOLIDARITES_PASSWORD = "password"
        settings.RDV_SOLIDARITES_TOKEN_EXPIRY = 86000
        settings.RDV_INSERTION_API_BASE_URL = "https://rdv-insertion.fake/api/v1/"
        respx.post(
            urljoin(settings.RDV_SOLIDARITES_API_BASE_URL, "auth/sign_in"), name="rdv_solidarites_sign_in"
        ).mock(
            return_value=httpx.Response(
                200, json=RDV_INSERTION_AUTH_SUCCESS_BODY, headers=RDV_INSERTION_AUTH_SUCCESS_HEADERS
            )
        )

    @respx.mock
    def test_renewal_success(self):
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].called

    @respx.mock
    def test_renewal_success_cache(self):
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1

        # Subsequent calls should hit the cache
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1

    @respx.mock
    def test_renewal_success_ignore_cache(self):
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1

        # Should not hit the cache with refresh=True
        credentials = get_api_credentials(refresh=True)
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 2

    @respx.mock
    def test_renewal_failure_rdvi_error(self):
        respx.routes["rdv_solidarites_sign_in"].mock(
            return_value=httpx.Response(401, json=RDV_INSERTION_AUTH_FAILURE_BODY)
        )
        with pytest.raises(httpx.HTTPStatusError):
            get_api_credentials()
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1
        assert cache.ttl(RDV_S_CREDENTIALS_CACHE_KEY) == 0  # Cache key not found (0: not found / None: no expiry)

        # Subsequent calls should not hit the cache for failed attempts
        with pytest.raises(httpx.HTTPStatusError):
            get_api_credentials()
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 2
        assert cache.ttl(RDV_S_CREDENTIALS_CACHE_KEY) == 0

    @respx.mock
    @override_settings(RDV_SOLIDARITES_API_BASE_URL=None)
    def test_renewal_failure_rdvi_misconfiguration(self):
        with pytest.raises(ImproperlyConfigured):
            get_api_credentials()
        assert not respx.routes["rdv_solidarites_sign_in"].called
        assert cache.ttl(RDV_S_CREDENTIALS_CACHE_KEY) == 0


class TestRdvInsertionApiUtils:
    def test_get_invitation_status_opened(self):
        invitation_dict = {"clicked": True}
        assert get_invitation_status(invitation_dict) == Invitation.Status.OPENED

    def test_get_invitation_status_delivered(self, subtests):
        for status in RDV_I_INVITATION_DELIVERED_STATUSES:
            invitation_dict = {"clicked": False, "delivery_status": status}
            with subtests.test(status=status):
                assert get_invitation_status(invitation_dict) == Invitation.Status.DELIVERED

    def test_get_invitation_status_not_delivered(self, subtests):
        for status in RDV_I_INVITATION_NOT_DELIVERED_STATUSES:
            invitation_dict = {"clicked": False, "delivery_status": status}
            with subtests.test(status=status):
                assert get_invitation_status(invitation_dict) == Invitation.Status.NOT_DELIVERED

    def test_get_invitation_status_logs_error_for_unknown_status(self, caplog):
        invitation_dict = {"clicked": False, "delivery_status": "unknown_status"}
        get_invitation_status(invitation_dict)
        assert "Invalid RDV-I invitation status: 'unknown_status' not in supported list" in caplog.messages


class TestInvitationRequestModel:
    def setup_method(self, **kwargs):
        organization = PrescriberOrganizationWithMembershipFactory(
            membership__user__first_name="Max", membership__user__last_name="Throughput"
        )
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sender=organization.active_members.get(),
            for_snapshot=True,
        )
        self.invitation_request = InvitationRequestFactory(
            job_seeker=self.job_application.job_seeker,
            company=self.job_application.to_company,
            email_invitation=None,
        )
        self.invitation_email = InvitationFactory(
            invitation_request=self.invitation_request,
            type=Invitation.Type.EMAIL,
            status=Invitation.Status.DELIVERED,
            rdv_insertion_id=1234,
        )
        self.invitation_sms = InvitationFactory(
            invitation_request=self.invitation_request,
            type=Invitation.Type.SMS,
            status=Invitation.Status.DELIVERED,
            rdv_insertion_id=1235,
        )

    def test_email_invitation_property(self):
        assert self.invitation_request.email_invitation == self.invitation_email

        self.invitation_email.delete()
        assert self.invitation_request.email_invitation is None

    def test_sms_invitation_property(self):
        assert self.invitation_request.sms_invitation == self.invitation_sms

        self.invitation_sms.delete()
        assert self.invitation_request.sms_invitation is None


class TestInvitationModel:
    def setup_method(self, **kwargs):
        self.invitation_request = InvitationRequestFactory(email_invitation=None)
        self.invitation_email = InvitationFactory(
            invitation_request=self.invitation_request,
            type=Invitation.Type.EMAIL,
            status=Invitation.Status.DELIVERED,
            rdv_insertion_id=1234,
        )
        self.invitation_sms = InvitationFactory(
            invitation_request=self.invitation_request,
            type=Invitation.Type.SMS,
            status=Invitation.Status.DELIVERED,
            rdv_insertion_id=1235,
        )
        self.invitation_postal = InvitationFactory(
            invitation_request=self.invitation_request,
            type=Invitation.Type.POSTAL,
            status=Invitation.Status.DELIVERED,
            rdv_insertion_id=1236,
        )

    def test_is_email_property(self):
        assert self.invitation_email.is_email
        assert not self.invitation_sms.is_email
        assert not self.invitation_postal.is_email

    def test_is_sms_property(self):
        assert not self.invitation_email.is_sms
        assert self.invitation_sms.is_sms
        assert not self.invitation_postal.is_sms

    def test_is_postal_property(self):
        assert not self.invitation_email.is_postal
        assert not self.invitation_sms.is_postal
        assert self.invitation_postal.is_postal


@freeze_time("2024-08-01")
class TestParticipationModel:
    def setup_method(self, freeze, **kwargs):
        organization = PrescriberOrganizationWithMembershipFactory(
            membership__user__first_name="Max", membership__user__last_name="Throughput"
        )
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sender=organization.active_members.get(),
            for_snapshot=True,
        )
        self.participation = ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            appointment__start_at=datetime.datetime(2024, 8, 1, 8, 0, tzinfo=datetime.UTC),
        )

    def test_get_status_display(self):
        # Status unknown and start_at in the future
        self.participation.status = Participation.Status.UNKNOWN
        assert self.participation.get_status_display() == "RDV à venir"

        # Status unknown and start_at in the past
        self.participation.appointment.start_at = datetime.datetime(2024, 7, 31, tzinfo=datetime.UTC)
        assert self.participation.get_status_display() == "Statut du RDV à préciser"

        self.participation.status = Participation.Status.SEEN
        assert self.participation.get_status_display() == Participation.Status.SEEN.label

        self.participation.status = Participation.Status.REVOKED
        assert self.participation.get_status_display() == Participation.Status.REVOKED.label

        self.participation.status = Participation.Status.EXCUSED
        assert self.participation.get_status_display() == Participation.Status.EXCUSED.label

        self.participation.status = Participation.Status.NOSHOW
        assert self.participation.get_status_display() == Participation.Status.NOSHOW.label

    def test_get_status_class_name(self):
        self.participation.status = Participation.Status.UNKNOWN
        assert self.participation.get_status_class_name() == "bg-important-lightest text-important"

        self.participation.status = Participation.Status.SEEN
        assert self.participation.get_status_class_name() == "bg-success-lighter text-success"

        self.participation.status = Participation.Status.REVOKED
        assert self.participation.get_status_class_name() == "bg-warning-lighter text-warning"

        self.participation.status = Participation.Status.EXCUSED
        assert self.participation.get_status_class_name() == "bg-warning-lighter text-warning"

        self.participation.status = Participation.Status.NOSHOW
        assert self.participation.get_status_class_name() == "bg-danger-lighter text-danger"


class TestWebhookEventModel:
    def setup_method(self, **kwargs):
        self.webhook_event_invitation = WebhookEventFactory()
        self.webhook_event_appointment = WebhookEventFactory(for_appointment=True)

    def test_for_invitation_property(self):
        assert self.webhook_event_invitation.for_invitation
        assert not self.webhook_event_appointment.for_invitation

    def test_for_appointment_property(self):
        assert not self.webhook_event_invitation.for_appointment
        assert self.webhook_event_appointment.for_appointment
