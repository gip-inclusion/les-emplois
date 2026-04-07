import datetime
import random
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.approvals.enums import ProlongationRequestStatus
from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.users.models import JobSeekerAssignment
from itou.www.job_seekers_views.views import can_see_external_job_applications
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import CompanyMembershipFactory, ContractFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.gps.factories import FollowUpGroupMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import get_request, parse_response_to_soup, pretty_indented


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


def test_not_a_job_seeker(client):
    not_a_job_seeker = random.choice(
        [PrescriberFactory(), EmployerFactory(), ItouStaffFactory(), LaborInspectorFactory()]
    )
    client.force_login(PrescriberFactory())
    url = reverse("job_seekers_views:details", kwargs={"public_id": not_a_job_seeker.public_id})
    response = client.get(url)
    assert response.status_code == 404


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
        criteria_kinds=[AdministrativeCriteriaKind.RSA, AdministrativeCriteriaKind.ZRR],
    )
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    iae_employer = CompanyMembershipFactory(company__subject_to_iae_rules=True).user

    client.force_login(prescriber_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with diag_and_update_eligibility")

    client.force_login(iae_employer)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with diag")

    non_iae_employer = CompanyMembershipFactory(company__not_subject_to_iae_rules=True).user

    client.force_login(non_iae_employer)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot without diag")


@freeze_time("2024-08-14")
def test_with_approval_and_diagnosis_from_employer(client, snapshot):
    """
    Employer diagnosis is not displayed to prescriber.
    """
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})
    approval = ApprovalFactory(user=job_seeker, number="XXXXX1212345", with_diagnosis_from_employer=True)

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
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="HTML page")


@freeze_time("2024-08-14")
def test_with_approval_and_diagnosis_from_prescriber(client, snapshot):
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})
    authorized_prescriber = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    ).user
    approval = ApprovalFactory(
        user=job_seeker,
        number="XXXXX1212345",
        eligibility_diagnosis__author=authorized_prescriber,
        eligibility_diagnosis__author_prescriber_organization=authorized_prescriber.prescriberorganization_set.first(),
        eligibility_diagnosis__with_job_seeker_assignment=True,
    )

    client.force_login(authorized_prescriber)
    with assertSnapshotQueries(snapshot(name="SQL queries")):
        response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/approvals/details/{approval.public_id}", "/approvals/details/[Public ID of Approval]"),
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="HTML page")


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
        criteria_kinds=[AdministrativeCriteriaKind.AAH, AdministrativeCriteriaKind.PM],
    )
    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    geiq_employer = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ).user

    client.force_login(geiq_employer)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with diag and details")

    client.force_login(prescriber_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with diag but without details")

    non_geiq_employer = CompanyMembershipFactory(company__subject_to_iae_rules=True).user
    client.force_login(non_geiq_employer)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot without diag")


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
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with GEIQ & IAE diag")


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
        company__subject_to_iae_rules=True,
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
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with both diag")

    client.force_login(geiq_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with GEIQ diag")

    client.force_login(iae_membership.user)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="snapshot with IAE diag")


@freeze_time("2024-08-14")
def test_job_application_tab(client, snapshot):
    prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    )
    job_application_1 = JobApplicationFactory(
        for_snapshot=True,
        sent_by_authorized_prescriber=True,
        sender_prescriber_organization=prescriber_membership.organization,
        sender=prescriber_membership.user,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
        with_iae_eligibility_diagnosis=True,
    )
    job_application_2 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-222222222222"),
        job_seeker=job_application_1.job_seeker,
        to_company__name="Autre Entreprise",
        sent_by_authorized_prescriber=True,
        sender_prescriber_organization=prescriber_membership.organization,
        sender=prescriber_membership.user,
        with_job_seeker_assignment=True,
    )
    client.force_login(prescriber_membership.user)
    url = reverse("job_seekers_views:job_applications", kwargs={"public_id": job_application_1.job_seeker.public_id})

    with assertSnapshotQueries(snapshot(name="SQL queries")):
        response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/company/{job_application_1.to_company.pk}/card", "/company/[PK of Company]/card"),
            ("href", f"/company/{job_application_2.to_company.pk}/card", "/company/[PK of Company]/card"),
        ],
    )
    assert pretty_indented(soup) == snapshot


@freeze_time("2024-08-14")
def test_apply_for_button_as_authorized_prescriber(client):
    authorized_prescriber = PrescriberMembershipFactory(organization__authorized=True).user

    job_application = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=authorized_prescriber,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
        job_seeker__with_mocked_address=True,
    )
    job_application_without_address = JobApplicationFactory(
        sent_by_prescriber_alone=True,
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
        sent_by_prescriber_alone=True,
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


@freeze_time("2024-08-14")
def test_display_job_seeker_referent(client, snapshot):
    prescriber = PrescriberFactory(
        membership=True,
        for_snapshot=True,
        membership__organization__name="Les Olivades",
        membership__organization__authorized=True,
    )
    job_seeker = JobSeekerFactory(for_snapshot=True)
    membership = FollowUpGroupMembershipFactory(
        follow_up_group__beneficiary=job_seeker,
        member=prescriber,
        started_at=datetime.date(2024, 1, 1),
    )
    group = membership.follow_up_group

    url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    client.force_login(prescriber)
    response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/gps/groups/{group.pk}/memberships", "/gps/groups/[PK of FollowUpGroup]"),
            ("href", f"/gps/groups/{group.pk}/edition", "/gps/groups/[PK of FollowUpGroup]/edition"),
            ("id", f"card-{prescriber.public_id}", "card-[Public ID of prescriber]"),
            (
                "hx-post",
                f"/gps/display/{group.pk}/{prescriber.public_id}/phone",
                "/gps/display/[PK of group]/[Public ID of participant]/phone",
            ),
            (
                "hx-post",
                f"/gps/display/{group.pk}/{prescriber.public_id}/email",
                "/gps/display/[PK of group]/[Public ID of participant]/email",
            ),
            ("id", f"phone-{prescriber.pk}", "phone-[PK of participant]"),
            ("id", f"email-{prescriber.pk}", "email-[PK of participant]"),
        ],
    )
    assert pretty_indented(soup) == snapshot()


@freeze_time("2024-08-14")
def test_job_application_tab_shows_external_application_to_authorized_prescriber(client, snapshot):
    prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True, organization__for_snapshot=True, organization__authorized=True
    )
    job_application_1 = JobApplicationFactory(
        for_snapshot=True,
        sent_by_authorized_prescriber=True,
        sender_prescriber_organization=prescriber_membership.organization,
        sender=prescriber_membership.user,
        created_at=timezone.now() + datetime.timedelta(seconds=10),  # Most recent, stabilize ordering.
        with_iae_eligibility_diagnosis=True,
        with_job_seeker_assignment=True,
    )
    # External job application (not from the prescriber's org).
    # Appears in the list, but without link to details.
    other_prescriber_membership = PrescriberMembershipFactory(
        organization__authorized=True,
        organization__name="L'Autre Organisation",
    )
    job_application_2 = JobApplicationFactory(
        sent_by_prescriber=True,
        pk=uuid.UUID("11111111-1111-1111-1111-222222222222"),
        job_seeker=job_application_1.job_seeker,
        to_company__name="Autre Entreprise",
        sender_prescriber_organization=other_prescriber_membership.organization,
        sender=other_prescriber_membership.user,
        with_job_seeker_assignment=True,
    )
    client.force_login(prescriber_membership.user)
    url = reverse("job_seekers_views:job_applications", kwargs={"public_id": job_application_1.job_seeker.public_id})

    with assertSnapshotQueries(snapshot(name="SQL queries")):
        response = client.get(url)
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/company/{job_application_1.to_company.pk}/card", "/company/[PK of Company]/card"),
            ("href", f"/company/{job_application_2.to_company.pk}/card", "/company/[PK of Company]/card"),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="HTML")


class TestCanSeeExternalJobApplication(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job_seeker = JobSeekerFactory()
        cls.authorized_prescriber = PrescriberFactory(
            membership=True,
            membership__organization__authorized=True,
        )

    def test_only_authorized_prescriber_can_see_external_job_applications(self):
        request = get_request(EmployerFactory())
        assert not can_see_external_job_applications(self.job_seeker, request)

    def test_authorized_prescriber_can_see_external_job_applications_if_approval_exists(self):
        org = self.authorized_prescriber.prescribermembership_set.get().organization
        request = get_request(self.authorized_prescriber)

        # No approval => not authorized
        assert not can_see_external_job_applications(self.job_seeker, request)

        # Approval by another organization => not authorized
        approval = ApprovalFactory(user=self.job_seeker)
        assert not can_see_external_job_applications(self.job_seeker, request)

        # Approval by the prescriber organization => authorized
        approval.eligibility_diagnosis.author_prescriber_organization = org
        approval.eligibility_diagnosis.save()
        assert can_see_external_job_applications(self.job_seeker, request)

    def test_authorized_prescriber_can_see_external_job_applications_if_recently_assigned(self):
        org = self.authorized_prescriber.prescribermembership_set.get().organization
        request = get_request(self.authorized_prescriber)

        # No application => not authorized
        assert not can_see_external_job_applications(self.job_seeker, request)

        # Only application is by another organization => not authorized
        _another_org_application = JobApplicationFactory(
            job_seeker=self.job_seeker,
            sent_by_authorized_prescriber=True,
            with_job_seeker_assignment=True,
        )
        assert not can_see_external_job_applications(self.job_seeker, request)

        # Own application, but too old => not authorized
        _too_old_application = JobApplicationFactory(
            job_seeker=self.job_seeker,
            sent_by_authorized_prescriber=True,
            sender_prescriber_organization=org,
            created_at=timezone.localtime() - datetime.timedelta(days=500),
            with_job_seeker_assignment=True,
        )
        assert not can_see_external_job_applications(self.job_seeker, request)

        # Own application is recent enough => authorized
        recent_application = JobApplicationFactory(
            job_seeker=self.job_seeker,
            sent_by_authorized_prescriber=True,
            sender_prescriber_organization=org,
            created_at=timezone.localtime() - datetime.timedelta(days=1),
        )
        assignment = JobSeekerAssignment.objects.filter(
            prescriber_organization=org,
        ).get()
        assignment.updated_at = recent_application.created_at
        assignment.save()
        assert can_see_external_job_applications(self.job_seeker, request)

    def test_authorized_prescriber_can_see_external_job_applications_if_recently_prolonged(self):
        approval = ApprovalFactory(user=self.job_seeker)
        org = self.authorized_prescriber.prescribermembership_set.get().organization
        request = get_request(self.authorized_prescriber)

        # No prolongation => not authorized
        assert not can_see_external_job_applications(self.job_seeker, request)

        # Prolongation by another organization => not authorized
        p = ProlongationRequestFactory(approval=approval)
        assert not can_see_external_job_applications(self.job_seeker, request)
        p.delete()  # prolongation model has non-overlapping constraints

        # Prolongation by the same org, but too old => not authorized
        p = ProlongationRequestFactory(
            approval=approval,
            prescriber_organization=org,
            created_at=timezone.localtime() - datetime.timedelta(days=500),
        )
        assert not can_see_external_job_applications(self.job_seeker, request)
        p.delete()  # prolongation model has non-overlapping constraints

        # Recent prolongation by the same or => authorized
        ProlongationRequestFactory(
            status=ProlongationRequestStatus.GRANTED,
            approval=approval,
            prescriber_organization=org,
            created_at=timezone.localtime() - datetime.timedelta(days=1),
        )
        assert can_see_external_job_applications(self.job_seeker, request)


class TestContracts:
    @freeze_time("2025-08-07")
    def test_for_authorized_prescriber(self, client, snapshot):
        approval = ApprovalFactory(
            for_snapshot=True,
            start_at="2025-01-01",
            end_at="2026-12-31",
        )
        job_seeker = approval.user
        authorized_prescriber = PrescriberFactory(
            membership=True,
            membership__organization__authorized=True,
        )

        # Not displayed contracts
        ContractFactory(start_date="2025-01-02")  # Contract on another job seeker
        ContractFactory(job_seeker=job_seeker, start_date="2024-12-01", end_date="2024-12-31")  # Before approval
        ContractFactory(job_seeker=job_seeker, start_date="2027-01-01", end_date="2027-06-30")  # After approval

        # Displayed contracts
        ContractFactory(
            company__name="Tif'any",
            job_seeker=job_seeker,
            start_date="2025-01-01",
            end_date="2025-08-07",
            company__kind=CompanyKind.EI,
        )  # Fully inside approval validity
        ContractFactory(
            company__name="Tralal’Hair",
            job_seeker=job_seeker,
            start_date="2025-02-01",
            end_date=None,
            company__kind=CompanyKind.EI,
        )  # start date inside approval validity
        ContractFactory(
            company__name="Faudra Tif Hair",
            job_seeker=job_seeker,
            start_date="2024-10-01",
            end_date="2025-01-10",
            company__kind=CompanyKind.EI,
        )  # end date inside approval validity
        ContractFactory(
            company__name="Inter Planet Hair",
            job_seeker=job_seeker,
            start_date="2024-10-01",
            end_date="2028-06-30",
            company__kind=CompanyKind.EI,
        )  # approval inside contract dates

        client.force_login(authorized_prescriber)
        response = client.get(reverse("job_seekers_views:contracts", kwargs={"public_id": job_seeker.public_id}))
        assert (
            pretty_indented(
                parse_response_to_soup(
                    response, "#main", replace_in_attr=[("href", str(approval.public_id), "[Public ID of Approval]")]
                )
            )
            == snapshot
        )

    def test_forbidden(self, client):
        job_seeker = JobSeekerFactory()
        for user, expected_status in [
            (LaborInspectorFactory(membership=True), 403),
            (PrescriberFactory(), 403),
            (PrescriberFactory(membership__organization__authorized=True), 200),
            (EmployerFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(reverse("job_seekers_views:contracts", kwargs={"public_id": job_seeker.public_id}))
            assert response.status_code == expected_status
