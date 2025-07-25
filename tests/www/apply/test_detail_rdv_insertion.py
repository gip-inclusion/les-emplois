import datetime
from urllib.parse import urljoin

import httpx
import pytest
import respx
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRaisesMessage, assertTemplateUsed

from itou.rdv_insertion.models import Appointment, InvitationRequest, Participation
from itou.utils.mocks.rdv_insertion import (
    RDV_INSERTION_AUTH_SUCCESS_HEADERS,
    RDV_INSERTION_CREATE_AND_INVITE_SUCCESS_BODY,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.rdv_insertion.factories import InvitationRequestFactory, ParticipationFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


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


@freeze_time("2024-08-01")
class TestRdvInsertionAppointmentsList:
    APPOINTMENTS_TAB_TITLE = "Rendez-vous"
    APPOINTMENTS_TAB_COUNTER = '<span id="upcoming-appointments-count"'
    APPOINTMENTS_TABLE_ID = '<table id="rdvi-appointments"'

    def setup_method(self, freeze, **kwargs):
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sent_by_authorized_prescriber_organisation=True,
            for_snapshot=True,
        )
        self.participation = ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            appointment__start_at=datetime.datetime(2024, 9, 1, 8, 0, tzinfo=datetime.UTC),
            for_snapshot=True,
        )

    @pytest.mark.parametrize(
        "profile,view_name,template_name",
        [
            ("employer", "apply:details_for_company", "process_details_company"),
            ("prescriber", "apply:details_for_prescriber", "process_details"),
            ("job_seeker", "apply:details_for_jobseeker", "process_details"),
        ],
    )
    def test_details_should_not_include_appointments_tab_if_not_configured_and_without_upcoming_appointments(
        self, profile_login, client, profile, view_name, template_name
    ):
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()
        self.participation.appointment.delete()

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertTemplateUsed(response, f"apply/{template_name}.html")
        assertNotContains(response, self.APPOINTMENTS_TAB_TITLE)

    @pytest.mark.parametrize(
        "profile,view_name,template_name",
        [
            ("employer", "apply:details_for_company", "process_details_company"),
            ("prescriber", "apply:details_for_prescriber", "process_details"),
            ("job_seeker", "apply:details_for_jobseeker", "process_details"),
        ],
    )
    def test_details_should_include_appointments_tab_if_not_configured_and_has_upcoming_appointments(
        self, profile_login, client, profile, view_name, template_name
    ):
        self.job_application.to_company.rdv_solidarites_id = None
        self.job_application.to_company.save()

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertTemplateUsed(response, f"apply/{template_name}.html")
        assertContains(response, self.APPOINTMENTS_TAB_TITLE)

    @pytest.mark.parametrize(
        "profile,view_name,template_name,contains_tab",
        [
            ("employer", "apply:details_for_company", "process_details_company", True),
            ("prescriber", "apply:details_for_prescriber", "process_details", False),
            ("job_seeker", "apply:details_for_jobseeker", "process_details", False),
        ],
    )
    def test_details_should_include_appointments_tab_if_configured_and_without_upcoming_appointments(
        self, profile_login, client, profile, view_name, template_name, contains_tab
    ):
        self.participation.appointment.delete()

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertTemplateUsed(response, f"apply/{template_name}.html")
        if contains_tab:
            assertContains(response, self.APPOINTMENTS_TAB_TITLE)
        else:
            assertNotContains(response, self.APPOINTMENTS_TAB_TITLE)

    @pytest.mark.parametrize(
        "profile,view_name,template_name",
        [
            ("employer", "apply:details_for_company", "process_details_company"),
            ("prescriber", "apply:details_for_prescriber", "process_details"),
            ("job_seeker", "apply:details_for_jobseeker", "process_details"),
        ],
    )
    def test_details_should_include_appointments_tab_if_configured_and_with_upcoming_appointments(
        self, profile_login, client, profile, view_name, template_name
    ):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertTemplateUsed(response, f"apply/{template_name}.html")
        assertContains(response, self.APPOINTMENTS_TAB_TITLE)

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_tab_should_not_display_appointments_table_when_no_appointments_exist(
        self, profile_login, client, profile, view_name
    ):
        self.participation.appointment.delete()

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertNotContains(response, self.APPOINTMENTS_TABLE_ID)

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_tab_should_display_appointments_table_when_appointments_exist(
        self, profile_login, client, profile, view_name
    ):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertContains(response, self.APPOINTMENTS_TABLE_ID)

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_tab_should_display_upcoming_appointments(self, profile_login, client, profile, view_name):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertContains(response, f'{self.APPOINTMENTS_TAB_COUNTER} class="badge badge-sm rounded-pill ms-2">1</span>')

        # Past participation
        ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.UNKNOWN,
            appointment__start_at=datetime.datetime(2024, 6, 3, 8, 0, tzinfo=datetime.UTC),
            status=Participation.Status.UNKNOWN,
        )
        # Future participation
        ParticipationFactory(
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.UNKNOWN,
            appointment__start_at=datetime.datetime(2024, 9, 2, 8, 0, tzinfo=datetime.UTC),
            status=Participation.Status.UNKNOWN,
        )

        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertContains(response, f'{self.APPOINTMENTS_TAB_COUNTER} class="badge badge-sm rounded-pill ms-2">2</span>')

        # Delete appointments
        self.job_application.job_seeker.rdvi_appointments.all().delete()
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        assertNotContains(response, self.APPOINTMENTS_TAB_COUNTER)

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_listing_display(self, profile_login, client, snapshot, profile, view_name):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        table = parse_response_to_soup(response, selector="#rdvi-appointments")
        assert pretty_indented(table) == snapshot()

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_listing_display_previous_appointments(
        self, profile_login, client, snapshot, profile, view_name
    ):
        ParticipationFactory(
            id="22222222-2222-2222-2222-222222222222",
            for_snapshot=True,
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.UNKNOWN,
            appointment__start_at=datetime.datetime(2024, 6, 1, 8, 0, tzinfo=datetime.UTC),
            appointment__rdv_insertion_id=4321,
            appointment__location__rdv_solidarites_id=4321,
            status=Participation.Status.UNKNOWN,
            rdv_insertion_id=4321,
        )

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        table = parse_response_to_soup(response, selector="#rdvi-appointments")
        assert pretty_indented(table) == snapshot()

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_listing_status_badges(self, profile_login, client, snapshot, profile, view_name):
        ParticipationFactory(
            id="22222222-2222-2222-2222-222222222222",
            for_snapshot=True,
            job_seeker=self.job_application.job_seeker,
            appointment__company=self.job_application.to_company,
            status=Participation.Status.SEEN,
            rdv_insertion_id=4321,
            appointment__status=Appointment.Status.SEEN,
            appointment__start_at=datetime.datetime(2024, 1, 4, 8, 0, tzinfo=datetime.UTC),
            appointment__rdv_insertion_id=4321,
            appointment__location__rdv_solidarites_id=4321,
        )
        ParticipationFactory(
            id="33333333-3333-3333-3333-333333333333",
            for_snapshot=True,
            job_seeker=self.job_application.job_seeker,
            status=Participation.Status.REVOKED,
            rdv_insertion_id=5432,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.REVOKED,
            appointment__start_at=datetime.datetime(2024, 1, 3, 8, 0, tzinfo=datetime.UTC),
            appointment__rdv_insertion_id=5432,
            appointment__location__rdv_solidarites_id=5432,
        )
        ParticipationFactory(
            id="44444444-4444-4444-4444-444444444444",
            for_snapshot=True,
            job_seeker=self.job_application.job_seeker,
            status=Participation.Status.EXCUSED,
            rdv_insertion_id=6543,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.EXCUSED,
            appointment__start_at=datetime.datetime(2024, 1, 2, 8, 0, tzinfo=datetime.UTC),
            appointment__rdv_insertion_id=6543,
            appointment__location__rdv_solidarites_id=6543,
        )
        ParticipationFactory(
            id="55555555-5555-5555-5555-555555555555",
            for_snapshot=True,
            job_seeker=self.job_application.job_seeker,
            status=Participation.Status.NOSHOW,
            rdv_insertion_id=7654,
            appointment__company=self.job_application.to_company,
            appointment__status=Appointment.Status.NOSHOW,
            appointment__start_at=datetime.datetime(2024, 1, 1, 8, 0, tzinfo=datetime.UTC),
            appointment__rdv_insertion_id=7654,
            appointment__location__rdv_solidarites_id=7654,
        )

        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))

        table = parse_response_to_soup(response, selector="#rdvi-appointments")
        assert pretty_indented(table) == snapshot()

    @pytest.mark.parametrize(
        "profile,view_name",
        [
            ("employer", "apply:details_for_company"),
            ("prescriber", "apply:details_for_prescriber"),
            ("job_seeker", "apply:details_for_jobseeker"),
        ],
    )
    def test_appointments_tooltips(self, profile_login, client, snapshot, profile, view_name):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))

        details_button = parse_response_to_soup(
            response, selector="#participation-11111111-1111-1111-1111-111111111111-row"
        )
        assert pretty_indented(details_button) == snapshot()


@freeze_time("2024-08-01")
class TestRdvInsertionInvitationRequestsList:
    @freeze_time("2024-07-01")
    def setup_method(self, freeze, **kwargs):
        self.job_application = JobApplicationFactory(
            to_company__name="Hit Pit",
            to_company__with_membership=True,
            to_company__rdv_solidarites_id=1234,
            job_seeker__first_name="Jacques",
            job_seeker__last_name="Henry",
            sent_by_authorized_prescriber_organisation=True,
            for_snapshot=True,
        )
        self.invitation_request = InvitationRequestFactory(
            job_seeker=self.job_application.job_seeker,
            company=self.job_application.to_company,
            for_snapshot=True,
        )

    @pytest.mark.parametrize(
        "profile,view_name,invitations_presence",
        [
            ("employer", "apply:details_for_company", True),
            ("prescriber", "apply:details_for_prescriber", False),
            ("job_seeker", "apply:details_for_jobseeker", False),
        ],
    )
    def test_invitations_requests_listing(
        self, profile_login, client, snapshot, profile, view_name, invitations_presence
    ):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        if invitations_presence:
            table = parse_response_to_soup(response, selector="#rdvi-invitation-requests")
            assert pretty_indented(table) == snapshot()
        else:
            # Selector not found
            with assertRaisesMessage(ValueError, "not enough values to unpack (expected 1, got 0)"):
                parse_response_to_soup(response, selector="#rdvi-invitation-requests")

    @pytest.mark.parametrize(
        "profile,view_name,contains_invite_button",
        [
            ("employer", "apply:details_for_company", True),
            ("prescriber", "apply:details_for_prescriber", False),
            ("job_seeker", "apply:details_for_jobseeker", False),
        ],
    )
    def test_invite_button_uses_for_detail_endpoint(
        self, profile_login, client, profile, view_name, contains_invite_button
    ):
        profile_login(profile, self.job_application)
        response = client.get(reverse(view_name, kwargs={"job_application_id": self.job_application.pk}))
        invite_button_url = reverse(
            "apply:rdv_insertion_invite_for_detail", kwargs={"job_application_id": self.job_application.pk}
        )
        if contains_invite_button:
            assertContains(response, invite_button_url)
        else:
            assertNotContains(response, invite_button_url)

    @respx.mock
    def test_invite_response_includes_updated_invitation_requests_listing_for_employer(self, client, snapshot, mocker):
        mocker.patch(
            "itou.www.apply.views.process_views.get_api_credentials", return_value=RDV_INSERTION_AUTH_SUCCESS_HEADERS
        )
        assert InvitationRequest.objects.count() == 1
        client.force_login(self.job_application.to_company.members.get())
        response = client.get(
            reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk})
        )
        table = parse_response_to_soup(response, selector="#rdvi-invitation-requests")
        assert pretty_indented(table) == snapshot(name="existing_invitation_requests")

        # Call the invite endpoint
        response = client.post(
            reverse("apply:rdv_insertion_invite_for_detail", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert InvitationRequest.objects.count() == 2
        invitation_requests_table = parse_response_to_soup(response, selector="#rdvi-invitation-requests")
        assert pretty_indented(invitation_requests_table) == snapshot(name="updated_invitation_requests")

    @respx.mock
    @pytest.mark.parametrize("profile", ["prescriber", "job_seeker"])
    def test_invite_fails_for_non_employers(self, profile_login, client, profile, mocker):
        mocker.patch(
            "itou.www.apply.views.process_views.get_api_credentials", return_value=RDV_INSERTION_AUTH_SUCCESS_HEADERS
        )
        assert InvitationRequest.objects.count() == 1
        profile_login(profile, self.job_application)

        # Call the invite endpoint
        response = client.post(
            reverse("apply:rdv_insertion_invite_for_detail", kwargs={"job_application_id": self.job_application.pk}),
            follow=True,
        )
        assert response.status_code == 403
        assert InvitationRequest.objects.count() == 1
