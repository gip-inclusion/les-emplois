import datetime
from urllib.parse import urljoin

import httpx
import pytest
import respx
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateNotUsed, assertTemplateUsed

from itou.rdv_insertion.models import Appointment, Invitation, InvitationRequest, Participation
from itou.utils.mocks.rdv_insertion import (
    RDV_INSERTION_AUTH_SUCCESS_HEADERS,
    RDV_INSERTION_CREATE_AND_INVITE_FAILURE_BODY,
    RDV_INSERTION_CREATE_AND_INVITE_SUCCESS_BODY,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.rdv_insertion.factories import InvitationRequestFactory, ParticipationFactory
from tests.utils.test import parse_response_to_soup


@pytest.fixture(autouse=True)
def mock_rdvs_api(settings):
    settings.RDV_SOLIDARITES_API_BASE_URL = "https://rdv-solidarites.fake/api/v1/"
    settings.RDV_SOLIDARITES_EMAIL = "tech@inclusion.beta.gouv.fr"
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


class TestRdvInsertionDisplay:
    SEE_JOB_APPLICATION_LABEL = "Voir sa candidature"
    SEE_JOB_APPLICATION_LABEL_FOR_JOB_SEEKER = "Voir ma candidature"
    INVITE_LABEL = "Proposer un rendez-vous"
    ONGOING_INVITE_LABEL = "Envoi en cours"
    INVITE_SENT_LABEL = "Invitation envoyée"
    NEXT_APPOINTMENT_LABEL = "Prochain rdv le 01/09/2024"
    OTHER_APPOINTMENTS_ONE_TOOLTIP_LABEL = "1 autre rendez-vous prévu, consultez-le dans le détail de candidature"
    OTHER_APPOINTMENTS_TWO_TOOLTIP_LABEL = "2 autres rendez-vous prévus, consultez-les dans le détail de candidature"

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
        self.participation = ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            appointment__start_at=datetime.datetime(2024, 9, 1, 8, 0, tzinfo=datetime.UTC),
            for_snapshot=True,
        )

    @pytest.mark.parametrize(
        "profile,view_name,job_application_label",
        [
            ("employer", "apply:list_for_siae", SEE_JOB_APPLICATION_LABEL),
            ("job_seeker", "apply:list_for_job_seeker", SEE_JOB_APPLICATION_LABEL_FOR_JOB_SEEKER),
        ],
    )
    def test_list_no_rdv_insertion_button_when_not_configured(
        self, profile_login, client, profile, view_name, job_application_label
    ):
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name))
        assertContains(response, job_application_label)
        assertTemplateNotUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")

    @pytest.mark.parametrize(
        "profile,view_name,job_application_label",
        [
            ("employer", "apply:list_for_siae", SEE_JOB_APPLICATION_LABEL),
            ("job_seeker", "apply:list_for_job_seeker", SEE_JOB_APPLICATION_LABEL_FOR_JOB_SEEKER),
        ],
    )
    def test_list_rdv_insertion_button_when_configured(
        self, profile_login, client, profile, view_name, job_application_label
    ):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name))
        assertContains(response, job_application_label)
        if profile == "employer":
            assertTemplateUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")
            assertContains(response, self.INVITE_LABEL)  # visible text
            assertContains(response, self.ONGOING_INVITE_LABEL)  # loader text, not visible
        else:
            assertTemplateNotUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")
            assertNotContains(response, self.INVITE_LABEL)
            assertNotContains(response, self.ONGOING_INVITE_LABEL)
        assertNotContains(response, self.INVITE_SENT_LABEL)

    @freeze_time("2024-07-29")
    @pytest.mark.parametrize(
        "profile,view_name,job_application_label",
        [
            ("employer", "apply:list_for_siae", SEE_JOB_APPLICATION_LABEL),
            ("job_seeker", "apply:list_for_job_seeker", SEE_JOB_APPLICATION_LABEL_FOR_JOB_SEEKER),
        ],
    )
    def test_list_rdv_insertion_button_when_configured_and_sent(
        self, profile_login, client, profile, view_name, job_application_label
    ):
        InvitationRequestFactory(
            job_seeker=self.job_application.job_seeker,
            company=self.job_application.to_company,
            created_at=timezone.now(),
        )

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name))
        assertContains(response, job_application_label)
        if profile == "employer":
            assertTemplateUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")
            assertContains(response, self.INVITE_SENT_LABEL)
        else:
            assertTemplateNotUsed(response, "apply/includes/buttons/rdv_insertion_invite.html")
            assertNotContains(response, self.INVITE_SENT_LABEL)
        assertNotContains(response, self.INVITE_LABEL)
        assertNotContains(response, self.ONGOING_INVITE_LABEL)

    @freeze_time("2024-08-01")
    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:list_for_siae"),
            ("job_seeker", "apply:list_for_job_seeker"),
        ],
    )
    def test_list_no_upcoming_appointments(self, profile_login, client, profile, view_name):
        self.participation.appointment.delete()
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name))
        assertTemplateUsed(response, "apply/includes/list_card_body.html")
        assertTemplateUsed(response, "apply/includes/next_appointment.html")
        assertNotContains(response, self.NEXT_APPOINTMENT_LABEL)
        assertNotContains(response, self.OTHER_APPOINTMENTS_ONE_TOOLTIP_LABEL)
        assertNotContains(response, self.OTHER_APPOINTMENTS_TWO_TOOLTIP_LABEL)

    @freeze_time("2024-08-01")
    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:list_for_siae"),
            ("job_seeker", "apply:list_for_job_seeker"),
        ],
    )
    def test_list_with_one_upcoming_appointment(self, profile_login, client, profile, view_name):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name))
        assertTemplateUsed(response, "apply/includes/list_card_body.html")
        assertTemplateUsed(response, "apply/includes/next_appointment.html")
        assertContains(response, self.NEXT_APPOINTMENT_LABEL)
        assertNotContains(response, self.OTHER_APPOINTMENTS_ONE_TOOLTIP_LABEL)
        assertNotContains(response, self.OTHER_APPOINTMENTS_TWO_TOOLTIP_LABEL)

    @freeze_time("2024-08-01")
    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:list_for_siae"),
            ("job_seeker", "apply:list_for_job_seeker"),
        ],
    )
    def test_list_with_many_upcoming_appointments(self, profile_login, client, profile, view_name):
        profile_login(profile, self.job_application)

        ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            status=Participation.Status.UNKNOWN,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.UNKNOWN,
            appointment__start_at=datetime.datetime(2024, 9, 2, 8, 0, tzinfo=datetime.UTC),
        )
        response = client.get(reverse(view_name))
        assertTemplateUsed(response, "apply/includes/list_card_body.html")
        assertTemplateUsed(response, "apply/includes/next_appointment.html")
        assertContains(response, self.NEXT_APPOINTMENT_LABEL)
        assertContains(response, self.OTHER_APPOINTMENTS_ONE_TOOLTIP_LABEL)
        assertNotContains(response, self.OTHER_APPOINTMENTS_TWO_TOOLTIP_LABEL)

        ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            status=Participation.Status.UNKNOWN,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.UNKNOWN,
            appointment__start_at=datetime.datetime(2024, 9, 3, 8, 0, tzinfo=datetime.UTC),
        )
        response = client.get(reverse(view_name))
        assertTemplateUsed(response, "apply/includes/list_card_body.html")
        assertTemplateUsed(response, "apply/includes/next_appointment.html")
        assertContains(response, self.NEXT_APPOINTMENT_LABEL)
        assertNotContains(response, self.OTHER_APPOINTMENTS_ONE_TOOLTIP_LABEL)
        assertContains(response, self.OTHER_APPOINTMENTS_TWO_TOOLTIP_LABEL)


class TestRdvInsertionView:
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
    def test_rdv_insertion_invite_not_available_for_job_seeker(self, client):
        client.force_login(self.job_application.job_seeker)
        response = client.post(
            reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert response.status_code == 404
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

        error_button = parse_response_to_soup(response, selector=".text-danger")
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
        assert invitation.status == invitation.Status.DELIVERED
        assert invitation.invitation_request == invitation_request
        assert response.context["job_application"] == self.job_application

        success_button = parse_response_to_soup(response, selector=".text-success")
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
            pending_request_exists = parse_response_to_soup(response, selector=".text-success")
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
            pending_request_exists = parse_response_to_soup(response, selector=".text-success")
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
            success_button = parse_response_to_soup(response, selector=".text-success")
            assert str(success_button) == snapshot(name="invitation_request_created")
