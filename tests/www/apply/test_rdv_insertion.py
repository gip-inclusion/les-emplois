import datetime
import json
from urllib.parse import urljoin

import httpx
import pytest
import respx
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.rdv_insertion.models import Invitation, InvitationRequest
from itou.utils.mocks.rdv_insertion import (
    RDV_INSERTION_AUTH_SUCCESS_HEADERS,
    RDV_INSERTION_CREATE_AND_INVITE_FAILURE_BODY,
    RDV_INSERTION_CREATE_AND_INVITE_SUCCESS_BODY,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.rdv_insertion.factories import InvitationRequestFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


@pytest.fixture(autouse=True)
def mock_rdvs_api(settings):
    settings.RDV_SOLIDARITES_API_BASE_URL = "https://rdv-solidarites.fake/api/v1/"
    settings.RDV_SOLIDARITES_EMAIL = "tech.emplois@inclusion.gouv.fr"
    settings.RDV_SOLIDARITES_PASSWORD = "password"
    settings.RDV_INSERTION_API_BASE_URL = "https://rdv-insertion.fake/api/v1/"
    settings.RDV_INSERTION_INVITE_HOLD_DURATION = datetime.timedelta(days=2)

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


class TestRdvInsertionView:
    def setup_method(self):
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sent_by_authorized_prescriber=True,
            for_snapshot=True,
        )

    @respx.mock
    @pytest.mark.parametrize("profile", ["prescriber", "job_seeker"])
    def test_rdv_insertion_invite_not_available_for_non_employers(self, profile_login, client, profile):
        profile_login(profile, self.job_application)
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert response.status_code == 403
        assert InvitationRequest.objects.count() == 0
        assert not respx.routes["rdv_solidarites_create_and_invite"].called

    @respx.mock
    def test_rdv_insertion_not_configured_for_employer(self, client, snapshot):
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

        error_button = parse_response_to_soup(response, selector=".text-danger")
        assert pretty_indented(error_button) == snapshot()

    @respx.mock
    def test_rdv_insertion_configured_invalid_job_application(self, client, snapshot):
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()
        other_job_application = JobApplicationFactory(sent_by_prescriber_alone=True)

        client.force_login(self.job_application.to_company.members.get())
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": other_job_application.pk}),
            follow=True,
        )
        assert InvitationRequest.objects.count() == 0
        assert not respx.routes["rdv_solidarites_create_and_invite"].called

        error_button = parse_response_to_soup(response, selector=".text-danger")
        assert pretty_indented(error_button) == snapshot()

    @pytest.mark.parametrize(
        "response_code,response_body",
        [
            [
                422,
                json.dumps(
                    {
                        "success": False,
                        "errors": [
                            {
                                "error_details": "Erreur en envoyant l'invitation par email: "
                                "Plusieurs catégories de motifs disponibles et aucune n'a été choisie"
                            }
                        ],
                    },
                ),
            ],
            [422, "not a JSON-encoded response"],
            [500, json.dumps(RDV_INSERTION_CREATE_AND_INVITE_FAILURE_BODY)],
        ],
    )
    @respx.mock
    def test_rdv_insertion_configured_with_failed_rdv_insertion_exchange(
        self, client, snapshot, mocker, response_code, response_body
    ):
        mocker.patch(
            "itou.www.apply.views.process_views.get_api_credentials", return_value=RDV_INSERTION_AUTH_SUCCESS_HEADERS
        )
        assert InvitationRequest.objects.count() == 0
        respx.routes["rdv_solidarites_create_and_invite"].mock(
            return_value=httpx.Response(response_code, content=response_body)
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
        assert pretty_indented(retry_button) == snapshot()

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
        assert invitation.status == invitation.Status.DELIVERED
        assert invitation.invitation_request == invitation_request
        assert response.context["job_application"] == self.job_application

        success_button = parse_response_to_soup(response, selector=".text-success")
        assert pretty_indented(success_button) == snapshot()

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
            pending_request_exists = parse_response_to_soup(response, selector=".text-success")
            assert pretty_indented(pending_request_exists) == snapshot(name="pending_invitation_request_too_recent")

            # Go to next tick
            frozen_time.move_to("2024-07-30T23:59:59Z")
            response = client.post(
                reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
                follow=True,
            )
            assert InvitationRequest.objects.count() == 1
            assert not respx.routes["rdv_solidarites_create_and_invite"].called
            assert response.context["job_application"] == self.job_application
            pending_request_exists = parse_response_to_soup(response, selector=".text-success")
            assert pretty_indented(pending_request_exists) == snapshot(
                name="pending_invitation_request_still_too_recent"
            )

            # Go to next tick
            frozen_time.move_to("2024-07-31T00:00:00Z")
            response = client.post(
                reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
                follow=True,
            )
            assert InvitationRequest.objects.count() == 2
            assert respx.routes["rdv_solidarites_create_and_invite"].called
            assert response.context["job_application"] == self.job_application
            success_button = parse_response_to_soup(response, selector=".text-success")
            assert pretty_indented(success_button) == snapshot(name="invitation_request_created")
