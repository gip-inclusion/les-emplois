import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.job_applications.factories import JobApplicationFactory


APPOINTMENTS_TAB = 'id="appointments-tab"'
RDV_INSERTION_INVITATIONS = 'id="rdvi-invitation-requests"'
NO_EMAIL_WARNING = "Aucun moyen de contacter ce candidat. Complétez ses informations via Modifier."


def details_url(job_application):
    return reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})


def propose_form(job_application):
    url = reverse("rdv_service_public:propose_appointment", kwargs={"job_application_id": job_application.pk})
    return f'action="{url}"'


class TestProposeAppointmentButton:
    @pytest.mark.parametrize("accepted", [False, True], ids=["pending", "accepted"])
    def test_buttons(self, client, accepted):
        job_application = JobApplicationFactory(
            to_company__allow_rdv_service_public=True,
            sent_by_authorized_prescriber=True,
            with_approval=accepted,
        )
        client.force_login(job_application.to_company.members.get())

        response = client.get(details_url(job_application))
        assertContains(response, APPOINTMENTS_TAB)
        # In the actions bar and in the appointments tab
        assertContains(response, propose_form(job_application), count=2)
        assertContains(
            response, "Cette candidature vous intéresse ? Proposez un entretien ou une réunion d’information."
        )
        assertNotContains(response, RDV_INSERTION_INVITATIONS)

    def test_job_seeker_without_email(self, client):
        job_application = JobApplicationFactory(
            to_company__allow_rdv_service_public=True,
            sent_by_authorized_prescriber=True,
            job_seeker__email=None,
        )
        client.force_login(job_application.to_company.members.get())

        response = client.get(details_url(job_application))
        assertNotContains(response, propose_form(job_application))
        assertContains(response, NO_EMAIL_WARNING, count=2)

    def test_company_not_allowed(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber=True)
        client.force_login(job_application.to_company.members.get())

        response = client.get(details_url(job_application))
        assertNotContains(response, APPOINTMENTS_TAB)
        assertNotContains(response, propose_form(job_application))

    def test_rdv_insertion_experiment(self, client):
        job_application = JobApplicationFactory(
            to_company__allow_rdv_service_public=True,
            to_company__rdv_solidarites_id=1234,
            sent_by_authorized_prescriber=True,
        )
        client.force_login(job_application.to_company.members.get())

        response = client.get(details_url(job_application))
        assertContains(response, RDV_INSERTION_INVITATIONS)
        assertNotContains(response, propose_form(job_application))
