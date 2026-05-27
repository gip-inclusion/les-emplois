import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.www.insertion_views.views import OrientationStep, OrientationWizardView
from tests.insertion.factories import ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.testing import get_session_name


def _select_job_seeker_url(service):
    return reverse("insertion_views:orientation_select_job_seeker", kwargs={"service_uid": service.uid})


def _start_url(service):
    return reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})


def _step_url(session_uuid, step):
    return reverse("insertion_views:orientation_steps", kwargs={"session_uuid": session_uuid, "step": step})


def _start_wizard(client, prescriber, job_seeker, service):
    client.force_login(prescriber)
    response = client.get(_start_url(service) + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    assertRedirects(response, _step_url(session_uuid, OrientationStep.CONFORMITY), fetch_redirect_response=False)
    return session_uuid


def test_start_without_job_seeker_and_select_from_list_resumes_orientation_wizard(client, db):
    prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    job_seeker = JobSeekerFactory()
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=prescriber)
    service = ServiceFactory(is_orientable_with_form=True)

    client.force_login(prescriber)
    response = client.post(
        _select_job_seeker_url(service),
        data={"job_seeker": job_seeker.public_id},
        follow=True,
    )

    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    assert response.request["PATH_INFO"] == _step_url(session_uuid, OrientationStep.CONFORMITY)


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


def test_start_creates_session_and_redirects_to_first_step(client, db):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)

    _start_wizard(client, prescriber, job_seeker, service)


def test_start_requires_login(client, db):
    service = ServiceFactory(is_orientable_with_form=True)

    response = client.get(_start_url(service))
    assert response.status_code == 302
    assert "/accounts/login" in response.headers["Location"]


def test_cancel_returns_to_service_card(client, db):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)

    session_uuid = _start_wizard(client, prescriber, job_seeker, service)
    response = client.get(_step_url(session_uuid, OrientationStep.CONFORMITY))
    assert response.context["reset_url"] == reverse(
        "insertion_views:service_card", kwargs={"service_uid": service.uid}
    )


def test_back_button_url_points_to_previous_step(client, db):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)

    session_uuid = _start_wizard(client, prescriber, job_seeker, service)
    client.post(_step_url(session_uuid, OrientationStep.CONFORMITY), {"confirms_conditions": "on"})
    response = client.get(_step_url(session_uuid, OrientationStep.REFERENT))
    assert response.context["wizard_steps"].prev == _step_url(session_uuid, OrientationStep.CONFORMITY)


@pytest.mark.parametrize(
    "current,next_step,post_data",
    [
        (OrientationStep.CONFORMITY, OrientationStep.REFERENT, {"confirms_conditions": "on"}),
        (
            OrientationStep.REFERENT,
            OrientationStep.DOCUMENTS,
            {
                "referent_last_name": "Dupont",
                "referent_first_name": "Jean",
                "referent_phone": "0612345678",
                "referent_email": "jean@example.com",
            },
        ),
    ],
)
def test_valid_post_advances_to_next_step(client, db, current, next_step, post_data):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)

    session_uuid = _start_wizard(client, prescriber, job_seeker, service)
    if current == OrientationStep.REFERENT:
        client.post(_step_url(session_uuid, OrientationStep.CONFORMITY), {"confirms_conditions": "on"})
    response = client.post(_step_url(session_uuid, current), post_data)
    assertRedirects(response, _step_url(session_uuid, next_step), fetch_redirect_response=False)


def test_session_isolation_between_users(client, db):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)
    intruder = PrescriberFactory(membership=True)

    session_uuid = _start_wizard(client, prescriber, job_seeker, service)
    client.force_login(intruder)
    response = client.get(_step_url(session_uuid, OrientationStep.CONFORMITY))
    assert response.status_code == 404
