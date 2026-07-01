from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.insertion.models import GenericReferenceItemKind
from itou.utils.apis.dora import DoraAPIException
from itou.www.insertion_views.views import OrientationStep, OrientationWizardView
from tests.insertion.factories import GenericReferenceItemFactory, ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.testing import get_session_name, parse_response_to_soup, pretty_indented


def test_orientation_wizard_happy_path(client, snapshot, mocker):
    prescriber = PrescriberMembershipFactory(
        organization__authorized=True,
        organization__for_snapshot=True,
        user__for_snapshot=True,
    ).user
    job_seeker = JobSeekerFactory(
        for_snapshot=True,
        email="usager@example.org",
        phone="0607080910",
        address_line_1="9 Allée des Peupliers",
        post_code="33000",
        city="Bordeaux",
    )
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=prescriber)
    fee = GenericReferenceItemFactory(
        kind=GenericReferenceItemKind.FEE,
        value="payant",
        label="20€",
    )
    public = GenericReferenceItemFactory(
        kind=GenericReferenceItemKind.PUBLIC,
        value="demandeur-emploi",
        label="Demandeur d'emploi",
    )
    service = ServiceFactory(
        uid="test-orientation-wizard-uid",
        name="Service orientation wizard",
        updated_on="2025-01-15",
        is_orientable_with_form=True,
        source__value="dora",
        structure__uid="test-structure-orientation-wizard-uid",
        structure__name="Structure orientation wizard",
        structure__updated_on="2025-01-15",
        fee=fee,
        fee_details="adhésion annuelle de 10€ à la MJC Champ Libre + frais de location",
        access_conditions_dora=["Résident QPV / ZFRR"],
        credentials=["Pièce d'identité", "Justificatif de domicile"],
    )
    service.publics.add(public)

    select_job_seeker_url = reverse(
        "insertion_views:orientation_select_job_seeker",
        kwargs={"service_uid": service.uid},
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    response = client.get(start_url)
    assertRedirects(response, select_job_seeker_url, fetch_redirect_response=False)

    response = client.get(select_job_seeker_url)
    assert pretty_indented(parse_response_to_soup(response, "#main .s-section")) == snapshot(name="select-job-seeker")

    response = client.post(select_job_seeker_url, data={"job_seeker": job_seeker.public_id}, follow=True)
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )
    assert response.request["PATH_INFO"] == conformity_url

    replace_session_uuid = [("href", session_uuid, "[UUID of session]"), ("action", session_uuid, "[UUID of session]")]
    response = client.get(conformity_url)
    assert pretty_indented(
        parse_response_to_soup(response, "#main .s-section", replace_in_attr=replace_session_uuid)
    ) == snapshot(name="conformity")

    response = client.post(conformity_url, {"confirms_conditions": "on"})
    referent_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.REFERENT},
    )
    assertRedirects(response, referent_url, fetch_redirect_response=False)

    response = client.get(referent_url)
    assert pretty_indented(
        parse_response_to_soup(response, "#main .s-section", replace_in_attr=replace_session_uuid)
    ) == snapshot(name="referent")

    response = client.post(
        referent_url,
        {
            "referent_last_name": "Dupont",
            "referent_first_name": "Jean",
            "referent_phone": "0612345678",
            "referent_email": "jean@example.com",
        },
    )
    documents_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.DOCUMENTS},
    )
    assertRedirects(response, documents_url, fetch_redirect_response=False)

    response = client.get(documents_url)
    assert pretty_indented(
        parse_response_to_soup(response, "#main .s-section", replace_in_attr=replace_session_uuid)
    ) == snapshot(name="documents")

    mock_dora = mocker.patch("itou.www.insertion_views.views.DoraAPIClient")
    response = client.post(
        documents_url,
        {
            "credentials_documents_files": SimpleUploadedFile("doc.pdf", b"x", content_type="application/pdf"),
            "credentials_proof_files": SimpleUploadedFile("proof.pdf", b"y", content_type="application/pdf"),
            "gdpr_consent": "on",
        },
    )
    confirmation_url = reverse(
        "insertion_views:orientation_confirmation",
        kwargs={"service_uid": service.uid},
        query={"job_seeker_public_id": job_seeker.public_id},
    )
    assertRedirects(response, confirmation_url, fetch_redirect_response=False)
    mock_dora.return_value.create_orientation.assert_called_once()

    response = client.get(confirmation_url)
    assert pretty_indented(parse_response_to_soup(response, "#main .s-section")) == snapshot(name="confirmation")


def test_documents_step_credential_documents(client):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(phone="0606060606")
    service = ServiceFactory(
        is_orientable_with_form=True,
        credentials_documents=[
            "production/eed8a0d4-238d-4921-a133-f5895e79fafb/flyer_PACEA_2025.pdf",
            "production/eed8a0d4-238d-4921-a133-f5895e79fafb/flyer_CEJ_2025.pdf",
        ],
        structure__name="Structure orientation wizard",
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )
    referent_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.REFERENT},
    )
    documents_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.DOCUMENTS},
    )

    client.post(conformity_url, {"confirms_conditions": "on"})
    client.post(
        referent_url,
        {
            "referent_last_name": "Dupont",
            "referent_first_name": "Jean",
            "referent_phone": "0612345678",
            "referent_email": "jean@example.com",
        },
    )

    s3_urls = [
        "https://s3.example.com/flyer_PACEA_2025.pdf?token=aaa",
        "https://s3.example.com/flyer_CEJ_2025.pdf?token=bbb",
    ]
    with patch(
        "itou.insertion.models.generate_dora_storage_url",
        side_effect=s3_urls,
    ):
        response = client.get(documents_url)

    assert response.status_code == 200
    assert response.context["credential_documents"] == [
        ("flyer_PACEA_2025.pdf", "https://s3.example.com/flyer_PACEA_2025.pdf?token=aaa"),
        ("flyer_CEJ_2025.pdf", "https://s3.example.com/flyer_CEJ_2025.pdf?token=bbb"),
    ]
    assertContains(response, "flyer_PACEA_2025.pdf")
    assertContains(response, "flyer_CEJ_2025.pdf")
    assertContains(response, "https://s3.example.com/flyer_PACEA_2025.pdf?token=aaa")
    assertNotContains(response, "production/eed8a0d4-238d-4921-a133-f5895e79fafb")


def test_start_requires_login(client):
    service = ServiceFactory(
        is_orientable_with_form=True,
        structure__name="Structure orientation wizard",
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    response = client.get(start_url)

    assert response.status_code == 302
    assert "/accounts/login" in response.headers["Location"]


def test_session_isolation_between_users(client):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(phone="0606060606")
    service = ServiceFactory(
        is_orientable_with_form=True,
        structure__name="Structure orientation wizard",
    )
    intruder = PrescriberFactory(membership=True)
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )

    client.force_login(intruder)
    response = client.get(conformity_url)

    assert response.status_code == 404


def test_orientation_wizard_shows_banner_and_generic_title(client):
    prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    job_seeker = JobSeekerFactory(first_name="Jane", last_name="Doe")
    service = ServiceFactory(is_orientable_with_form=True)
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )

    response = client.get(conformity_url)
    assertContains(response, "Vous orientez actuellement")
    assertContains(response, "vers un service")
    assertContains(response, "DOE Jane")
    assertContains(response, "<h1>Orienter vers un service d'insertion</h1>", html=True)


def test_conformity_step_blocks_when_beneficiary_info_is_incomplete(client, snapshot):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(first_name="", last_name="DUPONT", phone="0606060606", email="test@example.org")
    service = ServiceFactory(
        uid="test-orientation-incomplete-uid",
        name="Service orientation incomplete",
        updated_on="2025-01-15",
        is_orientable_with_form=True,
        structure__uid="test-structure-orientation-incomplete-uid",
        structure__name="Structure orientation wizard",
        structure__updated_on="2025-01-15",
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )

    response = client.post(conformity_url, {"confirms_conditions": "on"})

    assert response.status_code == 200
    assert (
        pretty_indented(
            parse_response_to_soup(
                response,
                "#main .s-section",
                replace_in_attr=[
                    ("href", session_uuid, "[UUID of session]"),
                    ("action", session_uuid, "[UUID of session]"),
                ],
            )
        )
        == snapshot
    )


def test_documents_step_redirects_to_error_page_when_orientation_submission_fails(client, mocker):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(phone="0606060606")
    service = ServiceFactory(
        is_orientable_with_form=True,
        structure__name="Structure orientation wizard",
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )
    referent_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.REFERENT},
    )
    documents_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.DOCUMENTS},
    )

    client.post(conformity_url, {"confirms_conditions": "on"})
    client.post(
        referent_url,
        {
            "referent_last_name": "Dupont",
            "referent_first_name": "Jean",
            "referent_phone": "0612345678",
            "referent_email": "jean@example.com",
        },
    )

    mock_dora = mocker.patch("itou.www.insertion_views.views.DoraAPIClient")
    mock_dora.return_value.create_orientation.side_effect = DoraAPIException

    response = client.post(
        documents_url,
        {
            "credentials_documents_files": SimpleUploadedFile("doc.pdf", b"x", content_type="application/pdf"),
            "credentials_proof_files": SimpleUploadedFile("proof.pdf", b"y", content_type="application/pdf"),
            "gdpr_consent": "on",
        },
    )
    assert response.status_code == 200
    assertContains(response, "problème technique")
    assert get_session_name(client.session, OrientationWizardView.expected_session_kind) == session_uuid


@pytest.mark.parametrize(
    "service_kwargs,expected_di_service_address_line",
    [
        (
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            "12 rue des terreaux, Bât. B, 38110 La Tour du Pin",
        ),
        ({}, "À distance"),
    ],
)
def test_documents_step_normalizes_beneficiary_phone_for_dora(
    client, mocker, service_kwargs, expected_di_service_address_line
):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(phone="+33601901570")
    service = ServiceFactory(
        is_orientable_with_form=True,
        contact_email="contact@example.org",
        structure__name="Structure orientation wizard",
        **service_kwargs,
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )
    referent_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.REFERENT},
    )
    documents_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.DOCUMENTS},
    )

    client.post(conformity_url, {"confirms_conditions": "on"})
    client.post(
        referent_url,
        {
            "referent_last_name": "Dupont",
            "referent_first_name": "Jean",
            "referent_phone": "0612345678",
            "referent_email": "jean@example.com",
        },
    )

    mock_dora = mocker.patch("itou.www.insertion_views.views.DoraAPIClient")

    client.post(
        documents_url,
        {
            "credentials_documents_files": SimpleUploadedFile("doc.pdf", b"x", content_type="application/pdf"),
            "credentials_proof_files": SimpleUploadedFile("proof.pdf", b"y", content_type="application/pdf"),
            "gdpr_consent": "on",
        },
    )

    payload, _ = mock_dora.return_value.create_orientation.call_args.args
    assert payload["beneficiary_phone"] == "0601901570"
    assert payload["di_contact_email"] == "contact@example.org"
    assert payload["di_service_address_line"] == expected_di_service_address_line


def test_conformity_step_allows_missing_beneficiary_phone(client):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(
        first_name="Jean",
        last_name="Dupont",
        phone="",
        email="test@example.org",
    )
    service = ServiceFactory(is_orientable_with_form=True)
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )

    response = client.post(conformity_url, {"confirms_conditions": "on"})
    referent_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.REFERENT},
    )
    assertRedirects(response, referent_url, fetch_redirect_response=False)


def test_orientation_banner_quitter_ignores_back_url(client):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)
    service_detail_url = (
        reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})
        + f"?job_seeker_public_id={job_seeker.public_id}&back_url=/search/services/results"
    )

    client.force_login(prescriber)
    response = client.get(service_detail_url)
    quit_link = parse_response_to_soup(response, 'a[aria-label="Quitter la procédure"]')
    assert quit_link["href"] == reverse("job_seekers_views:list")


def test_orientation_wizard_banner_quitter_goes_to_job_seekers_list(client):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()
    service = ServiceFactory(is_orientable_with_form=True)
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    client.get(start_url + f"?job_seeker_public_id={job_seeker.public_id}")
    session_uuid = get_session_name(client.session, OrientationWizardView.expected_session_kind)
    conformity_url = reverse(
        "insertion_views:orientation_steps",
        kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
    )

    response = client.get(conformity_url)
    quit_link = parse_response_to_soup(response, 'a[aria-label="Quitter la procédure"]')
    assert quit_link["href"] == reverse("job_seekers_views:list")
