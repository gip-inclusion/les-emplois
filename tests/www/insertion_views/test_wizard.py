import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.utils.apis.dora import DoraAPIException
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


def _reach_documents_step(client, prescriber, job_seeker, service):
    session_uuid = _start_wizard(client, prescriber, job_seeker, service)
    client.post(_step_url(session_uuid, OrientationStep.CONFORMITY), {"confirms_conditions": "on"})
    client.post(
        _step_url(session_uuid, OrientationStep.REFERENT),
        {
            "referent_last_name": "Dupont",
            "referent_first_name": "Jean",
            "referent_phone": "0612345678",
            "referent_email": "jean@example.com",
        },
    )
    return session_uuid


def _documents_post_data():
    return {
        "credentials_documents_files": SimpleUploadedFile("doc.pdf", b"x", content_type="application/pdf"),
        "credentials_proof_files": SimpleUploadedFile("proof.pdf", b"y", content_type="application/pdf"),
        "gdpr_consent": "on",
    }


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


def test_documents_step_uploads_to_dora_and_redirects_on_success(client, db, mocker):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)

    session_uuid = _reach_documents_step(client, prescriber, job_seeker, service)

    mock_dora = mocker.patch("itou.www.insertion_views.views.DoraAPIClient")

    response = client.post(_step_url(session_uuid, OrientationStep.DOCUMENTS), _documents_post_data())

    assertRedirects(
        response,
        reverse(
            "insertion_views:orientation_confirmation",
            kwargs={"service_uid": service.uid},
            query={"job_seeker_public_id": job_seeker.public_id},
        ),
        fetch_redirect_response=False,
    )
    mock_dora.return_value.create_orientation.assert_called_once()
    payload, attachments = mock_dora.return_value.create_orientation.call_args.args
    assert payload["di_service_id"] == service.uid
    assert "beneficiary_attachments" not in payload
    assert payload["data_protection_commitment"] is True
    assert payload["emplois_data"]["beneficiary_id"] == str(job_seeker.public_id)
    assert [name for name, _ in attachments] == ["doc.pdf", "proof.pdf"]


def test_documents_step_redirects_to_error_page_when_orientation_submission_fails(client, db, mocker):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)

    session_uuid = _reach_documents_step(client, prescriber, job_seeker, service)

    mock_dora = mocker.patch("itou.www.insertion_views.views.DoraAPIClient")
    mock_dora.return_value.create_orientation.side_effect = DoraAPIException

    response = client.post(_step_url(session_uuid, OrientationStep.DOCUMENTS), _documents_post_data())

    assertRedirects(
        response,
        reverse(
            "insertion_views:orientation_error",
            kwargs={"service_uid": service.uid},
            query={"job_seeker_public_id": job_seeker.public_id},
        ),
        fetch_redirect_response=False,
    )


def test_orientation_error_page(client, db):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(first_name="Michel", last_name="DURANT")
    service = ServiceFactory(is_orientable_with_form=True)

    client.force_login(prescriber)
    response = client.get(
        reverse(
            "insertion_views:orientation_error",
            kwargs={"service_uid": service.uid},
            query={"job_seeker_public_id": job_seeker.public_id},
        )
    )

    assert response.status_code == 200
    assertContains(response, "Orienter Michel DURANT vers un service d'insertion")
    assertContains(response, "Un problème technique est survenu")
    assertContains(response, "Votre demande n'a pas été transmise suite à un problème technique")
    assertContains(response, reverse("insertion_views:service_card", kwargs={"service_uid": service.uid}))


def test_orientation_confirmation_page(client, db):
    prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    job_seeker = JobSeekerFactory(email="boris@example.org")
    service = ServiceFactory(is_orientable_with_form=True)

    client.force_login(prescriber)
    response = client.get(
        reverse(
            "insertion_views:orientation_confirmation",
            kwargs={"service_uid": service.uid},
            query={"job_seeker_public_id": job_seeker.public_id},
        )
    )

    assert response.status_code == 200
    assertContains(response, "Votre demande a bien été transmise")
    assertContains(response, "boris@example.org")
    assertContains(response, "Retour à l'accueil")
    assertContains(response, reverse("dashboard:index"))
