from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from tests.insertion.factories import ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, PrescriberFactory


def _select_job_seeker_url(service):
    return reverse("insertion_views:orientation_select_job_seeker", kwargs={"service_uid": service.uid})


def _start_url(service):
    return reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})


def test_start_without_job_seeker_redirects_to_job_seeker_selection(client, db):
    prescriber = PrescriberFactory(membership=True)
    service = ServiceFactory(is_orientable_with_form=True)

    client.force_login(prescriber)
    response = client.get(_start_url(service))

    assertRedirects(
        response,
        _select_job_seeker_url(service),
        fetch_redirect_response=False,
    )


def test_orientation_select_job_seeker_page(client, db):
    prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    job_seeker = JobSeekerFactory(first_name="Michel", last_name="DURANT")
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=prescriber)
    service = ServiceFactory(is_orientable_with_form=True, name="Positiv - P+")

    client.force_login(prescriber)
    response = client.get(_select_job_seeker_url(service))

    assert response.status_code == 200
    assertContains(response, "Rechercher un usager")
    assertContains(response, 'id="id_job_seeker"')
    assertContains(response, "DURANT Michel")
    assertContains(response, "Positiv - P+")
    assertContains(response, "Créer un compte usager")
    assertContains(response, "tunnel=orientation")
    assertContains(response, f"service_uid={service.uid}")


def test_start_requires_login(client, db):
    service = ServiceFactory(is_orientable_with_form=True)

    response = client.get(_start_url(service))
    assert response.status_code == 302
    assert "/accounts/login" in response.headers["Location"]
