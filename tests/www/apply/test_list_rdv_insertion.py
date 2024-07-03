from datetime import timedelta
from urllib.parse import urljoin

import httpx
import pytest
import respx
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateNotUsed, assertTemplateUsed

from itou.rdv_insertion.models import Invitation, InvitationRequest
from itou.utils.mocks.rdv_insertion import (
    RDV_INSERTION_AUTH_SUCCESS_HEADERS,
    RDV_INSERTION_CREATE_AND_INVITE_FAILURE_BODY,
    RDV_INSERTION_CREATE_AND_INVITE_SUCCESS_BODY,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.rdv_insertion.factories import InvitationRequestFactory
from tests.utils.test import parse_response_to_soup


@pytest.fixture(autouse=True)
def mock_rdvs_api(settings):
    settings.RDV_SOLIDARITES_API_BASE_URL = "https://rdv-solidarites.fake/api/v1/"
    settings.RDV_SOLIDARITES_EMAIL = "tech@inclusion.beta.gouv.fr"
    settings.RDV_SOLIDARITES_PASSWORD = "password"
    settings.RDV_INSERTION_API_BASE_URL = "https://rdv-insertion.fake/api/v1/"
    settings.RDV_INSERTION_INVITE_HOLD_DURATION = timedelta(days=2)

    respx.post(
        urljoin(
            settings.RDV_INSERTION_API_BASE_URL,
            "organisations/1234/users/create_and_invite",
        ),
        name="rdv_solidarites_create_and_invite",
    ).mock(
        return_value=httpx.Response(
            200,
            json=RDV_INSERTION_CREATE_AND_INVITE_SUCCESS_BODY,
        )
    )


class TestRDVInsertionDisplay:
    SEE_JOB_APPLICATION_LABEL = "Voir sa candidature"
    INVITE_LABEL = "Proposer un rendez-vous"
    ONGOING_INVITE_LABEL = "Envoi en cours"
    INVITE_SENT_LABEL = "Invitation envoyée"

    def setup_method(self):
        org = PrescriberOrganizationWithMembershipFactory(
            membership__user__first_name="Max",
            membership__user__last_name="Throughput",
        )
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sender=org.active_members.get(),
            for_snapshot=True,
        )

    def test_list_no_rdv_insertion_button_when_not_configured(self, client):
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()

        client.force_login(self.job_application.to_company.members.get())
        response = client.get(reverse("apply:list_for_siae"))
        assertContains(response, self.SEE_JOB_APPLICATION_LABEL)
        assertTemplateNotUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")

    def test_list_rdv_insertion_button_when_configured(self, client):
        client.force_login(self.job_application.to_company.members.get())
        response = client.get(reverse("apply:list_for_siae"))
        assertContains(response, self.SEE_JOB_APPLICATION_LABEL)
        assertTemplateUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")
        assertContains(response, self.INVITE_LABEL)  # visible text
        assertContains(response, self.ONGOING_INVITE_LABEL)  # loader text, not visible
        assertNotContains(response, self.INVITE_SENT_LABEL)

    @freeze_time("2024-07-29")
    def test_list_rdv_insertion_button_when_configured_and_sent(self, client):
        InvitationRequestFactory(
            job_seeker=self.job_application.job_seeker,
            company=self.job_application.to_company,
            created_at=timezone.now(),
        )

        client.force_login(self.job_application.to_company.members.get())
        response = client.get(reverse("apply:list_for_siae"))
        assertContains(response, self.SEE_JOB_APPLICATION_LABEL)
        assertTemplateUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")
        assertNotContains(response, self.INVITE_LABEL)
        assertNotContains(response, self.ONGOING_INVITE_LABEL)
        assertContains(response, self.INVITE_SENT_LABEL)


class TestRDVInsertionView:
    def setup_method(self):
        org = PrescriberOrganizationWithMembershipFactory(
            membership__user__first_name="Max",
            membership__user__last_name="Throughput",
        )
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sender=org.active_members.get(),
            for_snapshot=True,
        )

    @respx.mock
    def test_rdv_insertion_not_configured(self, client, snapshot):
        assert InvitationRequest.objects.count() == 0
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()

        client.force_login(self.job_application.to_company.members.get())
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert InvitationRequest.objects.count() == 0
        assert not respx.routes["rdv_solidarites_create_and_invite"].called

        error_button = parse_response_to_soup(response, selector=".btn-danger")
        assert str(error_button) == snapshot()

    @respx.mock
    def test_rdv_insertion_configured_invalid_job_application(self, client, snapshot):
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()
        other_job_application = JobApplicationFactory()

        client.force_login(self.job_application.to_company.members.get())
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": other_job_application.pk}),
            follow=True,
        )
        assert InvitationRequest.objects.count() == 0
        assert not respx.routes["rdv_solidarites_create_and_invite"].called

        error_button = parse_response_to_soup(response, selector=".btn-danger")
        assert str(error_button) == snapshot()

    @respx.mock
    def test_rdv_insertion_configured_with_failed_rdv_insertion_exchange(self, client, snapshot, mocker):
        mocker.patch(
            "itou.www.apply.views.process_views.get_api_credentials", return_value=RDV_INSERTION_AUTH_SUCCESS_HEADERS
        )
        assert InvitationRequest.objects.count() == 0
        respx.routes["rdv_solidarites_create_and_invite"].mock(
            return_value=httpx.Response(500, json=RDV_INSERTION_CREATE_AND_INVITE_FAILURE_BODY)
        )

        client.force_login(self.job_application.to_company.members.get())
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert InvitationRequest.objects.count() == 0
        assert respx.routes["rdv_solidarites_create_and_invite"].called
        assert response.context["job_application"] == self.job_application

        retry_button = parse_response_to_soup(response, selector="form")
        assert str(retry_button) == snapshot()

    @respx.mock
    def test_rdv_insertion_configured_and_valid_rdv_insertion_exchange_with_no_pending_request(
        self, client, snapshot, mocker
    ):
        mocker.patch(
            "itou.www.apply.views.process_views.get_api_credentials", return_value=RDV_INSERTION_AUTH_SUCCESS_HEADERS
        )
        client.force_login(self.job_application.to_company.members.get())
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert respx.routes["rdv_solidarites_create_and_invite"].called
        invitation_request = InvitationRequest.objects.get()
        assert invitation_request.job_seeker == self.job_application.job_seeker
        assert invitation_request.company == self.job_application.to_company
        invitation = Invitation.objects.get()
        assert invitation.type == invitation.Type.EMAIL
        assert invitation.status == invitation.Status.SENT
        assert invitation.invitation_request == invitation_request
        assert response.context["job_application"] == self.job_application

        success_button = parse_response_to_soup(response, selector=".btn-success")
        assert str(success_button) == snapshot()

    @respx.mock
    def test_rdv_insertion_configured_and_valid_rdv_insertion_exchange_with_pending_request(
        self, client, snapshot, mocker
    ):
        mocker.patch(
            "itou.www.apply.views.process_views.get_api_credentials", return_value=RDV_INSERTION_AUTH_SUCCESS_HEADERS
        )
        with freeze_time("2024-07-29T00:00:00Z") as frozen_time:
            InvitationRequestFactory(
                job_seeker=self.job_application.job_seeker,
                company=self.job_application.to_company,
                created_at=timezone.now(),
            )
            assert InvitationRequest.objects.count() == 1

            client.force_login(self.job_application.to_company.members.get())
            response = client.post(
                reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
                follow=True,
            )

            assert InvitationRequest.objects.count() == 1
            assert not respx.routes["rdv_solidarites_create_and_invite"].called
            assert response.context["job_application"] == self.job_application
            pending_request_exists = parse_response_to_soup(response, selector=".btn-success")
            assert str(pending_request_exists) == snapshot(name="pending_invitation_request_too_recent")

            # Go to next tick
            frozen_time.move_to("2024-07-30T23:59:59Z")
            response = client.post(
                reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
                follow=True,
            )
            assert InvitationRequest.objects.count() == 1
            assert not respx.routes["rdv_solidarites_create_and_invite"].called
            assert response.context["job_application"] == self.job_application
            pending_request_exists = parse_response_to_soup(response, selector=".btn-success")
            assert str(pending_request_exists) == snapshot(name="pending_invitation_request_still_too_recent")

            # Go to next tick
            frozen_time.move_to("2024-07-31T00:00:00Z")
            response = client.post(
                reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
                follow=True,
            )
            assert InvitationRequest.objects.count() == 2
            assert respx.routes["rdv_solidarites_create_and_invite"].called
            assert response.context["job_application"] == self.job_application
            success_button = parse_response_to_soup(response, selector=".btn-success")
            assert str(success_button) == snapshot(name="invitation_request_created")
