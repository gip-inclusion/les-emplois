import datetime
import uuid

from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.companies.enums import CompanyKind
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyMembershipFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


def test_anonymous_user(client):
    job_seeker = JobSeekerFactory()
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})
    response = client.get(url)
    assertRedirects(response, reverse("account_login") + f"?next={url}")


def test_refused_access(client):
    job_seeker = JobSeekerFactory()
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    for user in [job_seeker, LaborInspectorFactory(membership=True)]:
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 403


@freeze_time("2024-08-14")
def test_single_iae_diag_from_prescriber(client, snapshot):
    job_seeker = JobSeekerFactory(for_snapshot=True)

    prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    )

    IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        from_prescriber=True,
        author_prescriber_organization=prescriber_membership.organization,
        author=prescriber_membership.user,
    )
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    iae_employer = CompanyMembershipFactory(company__subject_to_eligibility=True).user

    client.force_login(prescriber_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with diag_and_update_eligibility")

    client.force_login(iae_employer)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with diag")

    non_iae_employer = CompanyMembershipFactory(company__not_subject_to_eligibility=True).user

    client.force_login(non_iae_employer)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot without diag")


@freeze_time("2024-08-14")
def test_with_approval(client, snapshot):
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})
    approval = ApprovalFactory(user=job_seeker, for_snapshot=True)

    authorized_prescriber = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    ).user
    client.force_login(authorized_prescriber)
    with assertSnapshotQueries(snapshot(name="SQL queries")):
        response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/approvals/details/{approval.public_id}", "/approvals/details/[Public ID of Approval]"),
        ],
    )
    assert str(soup) == snapshot(name="HTML page")


@freeze_time("2024-08-14")
def test_single_geiq_diag_from_prescriber(client, snapshot):
    job_seeker = JobSeekerFactory(for_snapshot=True)

    prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    )

    GEIQEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        from_prescriber=True,
        author_prescriber_organization=prescriber_membership.organization,
        author=prescriber_membership.user,
    )
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    geiq_employer = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ).user

    client.force_login(geiq_employer)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with diag and details")

    client.force_login(prescriber_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with diag but without details")

    non_geiq_employer = CompanyMembershipFactory(company__subject_to_eligibility=True).user
    client.force_login(non_geiq_employer)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot without diag")


@freeze_time("2024-08-14")
def test_both_diag_from_prescriber(client, snapshot):
    job_seeker = JobSeekerFactory(for_snapshot=True)

    prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    )

    GEIQEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        from_prescriber=True,
        author_prescriber_organization=prescriber_membership.organization,
        author=prescriber_membership.user,
    )
    IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        from_prescriber=True,
        author_prescriber_organization=prescriber_membership.organization,
        author=prescriber_membership.user,
    )
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    client.force_login(prescriber_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with GEIQ & IAE diag")


@freeze_time("2024-08-14")
def test_both_diag_from_company(client, snapshot):
    job_seeker = JobSeekerFactory(for_snapshot=True)

    geiq_membership = CompanyMembershipFactory(
        company__kind=CompanyKind.GEIQ,
        company__for_snapshot=True,
        user__for_snapshot=True,
    )
    GEIQEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        from_employer=True,
        author_geiq=geiq_membership.company,
        author=geiq_membership.user,
    )
    iae_membership = CompanyMembershipFactory(
        company__subject_to_eligibility=True,
        company__for_snapshot=True,
        user__for_snapshot=True,
        user__public_id=uuid.uuid4(),
        user__email="un@autre.email",
    )
    IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        from_employer=True,
        author_siae=iae_membership.company,
        author=iae_membership.user,
    )
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    authorized_prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    client.force_login(authorized_prescriber)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with both diag")

    client.force_login(geiq_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with GEIQ diag")

    client.force_login(iae_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#main")
    assert str(soup) == snapshot(name="snapshot with IAE diag")


@freeze_time("2024-08-14")
def test_job_application_tab(client, snapshot):
    prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    )
    job_application_1 = JobApplicationFactory(
        for_snapshot=True,
        sent_by_authorized_prescriber_organisation=True,
        sender_prescriber_organization=prescriber_membership.organization,
        sender=prescriber_membership.user,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
    )
    job_application_2 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-222222222222"),
        job_seeker=job_application_1.job_seeker,
        to_company__name="Autre Entreprise",
        sent_by_authorized_prescriber_organisation=True,
        sender_prescriber_organization=prescriber_membership.organization,
        sender=prescriber_membership.user,
    )
    client.force_login(prescriber_membership.user)
    url = reverse("job_seekers_views:job_applications", kwargs={"public_id": job_application_1.job_seeker.public_id})

    with assertSnapshotQueries(snapshot(name="job seeker job applications view with sent job applications")):
        response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/company/{job_application_1.to_company.pk}/card", "/company/[PK of Company]/card"),
            ("href", f"/company/{job_application_2.to_company.pk}/card", "/company/[PK of Company]/card"),
        ],
    )
    assert str(soup) == snapshot


@freeze_time("2024-08-14")
def test_apply_for_button_as_authorized_prescriber(client):
    authorized_prescriber = PrescriberMembershipFactory(organization__authorized=True).user

    job_application = JobApplicationFactory(
        sender=authorized_prescriber,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
        job_seeker__with_mocked_address=True,
    )
    job_application_without_address = JobApplicationFactory(
        sender=authorized_prescriber,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
    )
    client.force_login(authorized_prescriber)
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_application.job_seeker.public_id})

    response = client.get(url)
    assertContains(
        response,
        (
            f'<a href="{reverse("search:employers_results")}'
            f'?job_seeker_public_id={job_application.job_seeker.public_id}&city={job_application.job_seeker.city_slug}"'
            'data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"'
            'data-matomo-option="postuler-pour-ce-candidat" class="btn btn-lg btn-primary btn-ico">'
            '<i class="ri-draft-line fw-medium" aria-hidden="true"></i>'
            "<span>Postuler pour ce candidat</span>"
            "</a>"
        ),
        html=True,
    )

    # No address
    url = reverse(
        "job_seekers_views:details", kwargs={"public_id": job_application_without_address.job_seeker.public_id}
    )
    response = client.get(url)
    assertContains(
        response,
        (
            f'<a href="{reverse("search:employers_results")}'
            f'?job_seeker_public_id={job_application_without_address.job_seeker.public_id}" '
            'data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"'
            'data-matomo-option="postuler-pour-ce-candidat" class="btn btn-lg btn-primary btn-ico">'
            '<i class="ri-draft-line fw-medium" aria-hidden="true"></i>'
            "<span>Postuler pour ce candidat</span>"
            "</a>"
        ),
        html=True,
    )


@freeze_time("2024-08-14")
def test_apply_for_button_as_unauthorized_prescriber(client):
    unauthorized_prescriber = PrescriberMembershipFactory(organization__authorized=False).user

    job_application = JobApplicationFactory(
        sender=unauthorized_prescriber,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
        job_seeker__with_mocked_address=True,
    )
    client.force_login(unauthorized_prescriber)
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_application.job_seeker.public_id})

    # User cannot view personal information
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_application.job_seeker.public_id})
    client.force_login(unauthorized_prescriber)

    response = client.get(url)
    assertContains(
        response,
        (
            f'<a href="{reverse("search:employers_results")}'
            f'?job_seeker_public_id={job_application.job_seeker.public_id}"'
            'data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"'
            'data-matomo-option="postuler-pour-ce-candidat" class="btn btn-lg btn-primary btn-ico">'
            '<i class="ri-draft-line fw-medium" aria-hidden="true"></i>'
            "<span>Postuler pour ce candidat</span>"
            "</a>"
        ),
        html=True,
    )


def test_update_iae_eligibility_buttons(client):
    update_eligibility_str = "Mettre à jour son éligibilité IAE"
    validate_eligibility_str = "Valider son éligibilité IAE"

    authorized_prescriber = PrescriberFactory(membership__organization__authorized=True)
    unauthorized_prescriber = PrescriberFactory(membership__organization__authorized=False)

    job_seeker = JobSeekerFactory()
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    # A unauthorized prescriber doesn't see the button
    client.force_login(unauthorized_prescriber)
    response = client.get(url)
    assertNotContains(response, update_eligibility_str)
    assertNotContains(response, validate_eligibility_str)

    # A authorized prescriber will the see the validate button as the jobseeker has no diagnostic
    client.force_login(authorized_prescriber)
    response = client.get(url)
    assertNotContains(response, update_eligibility_str)
    assertContains(response, validate_eligibility_str)

    # Same if the jobseeker has an old approval and diagnostic :
    ApprovalFactory(
        user=job_seeker,
        start_at=datetime.date(2021, 1, 1),
        eligibility_diagnosis__expired=True,
    )
    response = client.get(url)
    assertNotContains(response, update_eligibility_str)
    assertContains(response, validate_eligibility_str)

    # With a valid diagnostic, we see the update button
    IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True)
    response = client.get(url)
    assertContains(response, update_eligibility_str)
    assertNotContains(response, validate_eligibility_str)

    # With a valid Approval, no link
    ApprovalFactory(user=job_seeker)
    response = client.get(url)
    assertNotContains(response, update_eligibility_str)
    assertNotContains(response, validate_eligibility_str)
