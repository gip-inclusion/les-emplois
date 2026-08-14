from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.insertion.models import GenericReferenceItemKind, MobilizationEventKind, Orientation
from itou.job_applications.enums import SenderKind
from itou.www.insertion_views.views import OrientationStep, OrientationWizardView
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.insertion.factories import GenericReferenceItemFactory, MobilizationEventFactory, ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.testing import get_session_name, parse_response_to_soup, pretty_indented


def test_orientation_wizard_happy_path(client, snapshot):
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

    orientation = Orientation.objects.get()
    assert orientation.beneficiary == job_seeker
    assert orientation.sender == prescriber
    assert orientation.sender_kind == SenderKind.PRESCRIBER
    assert orientation.sender_prescriber_organization == prescriber.prescribermembership_set.get().organization
    assert orientation.sender_company is None
    assert orientation.service == service
    assert orientation.referent_first_name == "Jean"
    assert orientation.referent_last_name == "Dupont"
    assert orientation.referent_email == "jean@example.com"
    assert orientation.referent_phone == "0612345678"
    assert orientation.data_protection_commitment is True
    # assert orientation.attachments == [
    #     "orientations/attachments/doc.pdf",
    #     "orientations/attachments/proof.pdf",
    # ] # TODO

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


@pytest.mark.parametrize("is_blacklisted, status_code", [(True, 404), (False, 302)])
def test_start_with_non_orientable_di_sources(client, settings, is_blacklisted, status_code):
    prescriber = PrescriberFactory(membership=True)
    source_value = "source-name"
    if is_blacklisted:
        settings.NON_ORIENTABLE_DI_SOURCES = [source_value]
    service = ServiceFactory(is_orientable_with_form=True, source__value=source_value)
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})
    client.force_login(prescriber)

    response = client.get(start_url)
    assert response.status_code == status_code


def test_start_orientation_redirects_when_external_link_preferred(client):
    # A DI service that both is form-orientable and has an external link prefers the link:
    # direct access to the form flow must bounce back to the service detail page.
    prescriber = PrescriberFactory(membership=True)
    service = ServiceFactory(
        is_orientable_with_form=True,
        source__value="other",
        mobilization_modes_professionals_external_form_link="https://test.example.com",
    )
    assert service.should_mobilize_via_external_link
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})
    service_detail_url = reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})
    client.force_login(prescriber)

    response = client.get(start_url)
    assertRedirects(response, service_detail_url, fetch_redirect_response=False)


def test_orientation_select_job_seeker_redirects_when_external_link_preferred(client):
    prescriber = PrescriberFactory(membership=True)
    service = ServiceFactory(
        is_orientable_with_form=True,
        source__value="other",
        mobilization_modes_professionals_external_form_link="https://test.example.com",
    )
    assert service.should_mobilize_via_external_link
    select_url = reverse("insertion_views:orientation_select_job_seeker", kwargs={"service_uid": service.uid})
    service_detail_url = reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})
    client.force_login(prescriber)

    response = client.get(select_url)
    assertRedirects(response, service_detail_url, fetch_redirect_response=False)


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


def test_orientation_wizard_happy_path_as_employer(client):
    organization = CompanyFactory()
    user = CompanyMembershipFactory(company=organization).user
    job_seeker = JobSeekerFactory(
        first_name="Jean",
        last_name="Dupont",
        email="usager@example.org",
        phone="",
    )
    JobSeekerAssignmentFactory(professional=user, company=organization, job_seeker=job_seeker)
    service = ServiceFactory(is_orientable_with_form=True, structure__name="Structure orientation employeur")
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})

    client.force_login(user)
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

    client.post(documents_url, {"gdpr_consent": "on"})

    orientation = Orientation.objects.get()
    assert orientation.sender == user
    assert orientation.sender_kind == SenderKind.EMPLOYER
    assert orientation.sender_company == organization
    assert orientation.sender_prescriber_organization is None
    assert orientation.attachments == []


def test_orientation_wizard_links_latest_unlinked_mobilization_event(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    prescriber = membership.user
    organization = membership.organization
    job_seeker = JobSeekerFactory(first_name="Jean", last_name="Dupont", email="usager@example.org")
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=prescriber)
    service = ServiceFactory(is_orientable_with_form=True)
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

    session_key = client.session.session_key
    event_kwargs = {
        "kind": MobilizationEventKind.SERVICE_ORIENTATION,
        "session_key": session_key,
        "user": prescriber,
        "prescriber_organization": organization,
    }
    with freeze_time(timezone.now() - timedelta(hours=1)):
        older_event = MobilizationEventFactory(service=service, structure=service.structure, **event_kwargs)
    latest_event = MobilizationEventFactory(service=service, structure=service.structure, **event_kwargs)
    # An iMER for another service must not be linked.
    other_service = ServiceFactory(is_orientable_with_form=True)
    other_event = MobilizationEventFactory(service=other_service, structure=other_service.structure, **event_kwargs)

    client.post(documents_url, {"gdpr_consent": "on"})

    orientation = Orientation.objects.get()
    latest_event.refresh_from_db()
    older_event.refresh_from_db()
    other_event.refresh_from_db()
    assert latest_event.orientation == orientation
    assert older_event.orientation is None
    assert other_event.orientation is None


def test_orientation_select_job_seeker_lists_company_beneficiaries_for_employer(client):
    company = CompanyFactory()
    employer = CompanyMembershipFactory(company=company).user
    coworker = CompanyMembershipFactory(company=company).user
    job_seeker = JobSeekerFactory(first_name="Jean", last_name="Dupont")
    JobSeekerAssignmentFactory(professional=coworker, company=company, job_seeker=job_seeker)
    service = ServiceFactory(is_orientable_with_form=True)
    select_job_seeker_url = reverse(
        "insertion_views:orientation_select_job_seeker",
        kwargs={"service_uid": service.uid},
    )

    client.force_login(employer)
    response = client.get(select_job_seeker_url)

    assertContains(response, job_seeker.get_inverted_full_name())


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


def test_no_error_when_special_chars_in_uid(client):
    """Check that reset url and redirection to orientation_select_job_seeker have encoded uids"""
    prescriber = PrescriberFactory(membership=True)
    service = ServiceFactory(
        is_orientable_with_form=True,
        structure__name="Structure orientation wizard",
        uid="fredo--97416_13643-activités / ateliers",  # real case
    )
    start_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})
    select_job_seeker_url = reverse(
        "insertion_views:orientation_select_job_seeker", kwargs={"service_uid": service.uid}
    )
    service_url = reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})

    client.force_login(prescriber)
    response = client.get(start_url)
    assertRedirects(response, select_job_seeker_url, fetch_redirect_response=False)
    response = client.get(select_job_seeker_url)
    assertContains(response, service_url)  # reset button


def test_orientation_create_job_seeker_starts_with_search_by_email(client):
    prescriber = PrescriberFactory(membership=True)
    service = ServiceFactory(is_orientable_with_form=True)
    create_job_seeker_url = reverse(
        "job_seekers_views:get_or_create_start",
        query={
            "tunnel": "orientation",
            "from_url": reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid}),
            "service_uid": service.uid,
        },
    )

    client.force_login(prescriber)
    response = client.get(create_job_seeker_url)

    job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
    assertRedirects(
        response,
        reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        ),
        fetch_redirect_response=False,
    )
