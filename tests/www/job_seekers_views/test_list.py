import datetime
import uuid
from collections import Counter
from functools import partial

import factory
import pytest
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.asp.models import Commune
from itou.companies.models import Company
from itou.job_applications.enums import JobApplicationState
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import ActionKind
from itou.users.models import JobSeekerAssignment, User, UserKind
from itou.utils.templatetags.str_filters import mask_unless
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    CompanyWith2MembershipsFactory,
    ContractFactory,
)
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
)
from tests.users.factories import (
    EmployerFactory,
    JobSeekerAssignmentFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    ProfessionalFactory,
)
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import PAGINATION_PAGE_ONE_MARKUP, parse_response_to_soup, pretty_indented
from tests.www.apply.test_list_for_siae import SUSPENDED_APPROVAL_PRESCRIBER_TOOLTIP_MARKUP
from tests.www.apply.test_submit import fake_session_initialization


def assert_contains_button_apply_for(response, job_seeker, with_city=True, with_personal_information=True):
    city = f"&city={job_seeker.city_slug}" if with_city else ""
    # If personal information is not visible, the name should be masked in aria-label
    if with_personal_information:
        aria_label = job_seeker.get_inverted_full_name()
    else:
        aria_label = mask_unless(job_seeker.get_inverted_full_name(), False)
    assertContains(
        response,
        f"""
            <a class="btn btn-sm btn-link btn-ico-only"
                data-bs-toggle="tooltip"
                data-bs-title="Postuler pour cet usager"
                data-matomo-event="true"
                data-matomo-category="candidature" data-matomo-action="clic"
                data-matomo-option="postuler-pour-ce-candidat"
                href="{reverse("search:employers_results")}?job_seeker_public_id={job_seeker.public_id}{city}">
                <i class="ri-draft-line" aria-label="Postuler pour {aria_label}"></i>
            </a>
        """,
        count=1,
        html=True,
    )


def assert_contains_job_seeker(
    response, job_seeker, back_url=reverse("job_seekers_views:list"), with_personal_information=True
):
    assertContains(
        response,
        f"""
            <a href="{reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})}?back_url={
            back_url
        }" class="btn-link">{mask_unless(job_seeker.get_inverted_full_name(), with_personal_information)}
            </a>
        """,
        count=1,
        html=True,
    )


def assert_update_eligibility(response, can_update):
    assert_function = assertContains if can_update else assertNotContains
    assert_function(response, "Mettre à jour son éligibilité IAE")
    assert_function(response, "Valider son éligibilité IAE")


def assert_contains_last_advisor(response, job_seeker_assignment):
    if job_seeker_assignment.assigned_to_unknown_advisor:
        last_advisor_name = "Non précisé"
    else:
        last_advisor_name = job_seeker_assignment.professional.get_inverted_full_name()
    last_advisor_org = job_seeker_assignment.prescriber_organization or job_seeker_assignment.company
    last_advisor_org_name = (last_advisor_org and last_advisor_org.name) or "Non précisé"
    assertContains(response, f"{last_advisor_name} ({last_advisor_org_name})")


def assert_contains_button_advisor_self_assign(response, job_seeker, is_last_advisor):
    form_url = reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": job_seeker.public_id})
    assertion = assertNotContains if is_last_advisor else assertContains
    assertion(response, form_url)


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_anonymous_user(client, url):
    response = client.get(url)
    assertRedirects(response, reverse("account_login") + f"?next={url}")


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_refused_access(client, url):
    forbidden_users = [
        JobSeekerFactory(),
        LaborInspectorFactory(membership=True),
    ]
    if url == reverse("job_seekers_views:list"):
        forbidden_users.append(EmployerFactory(membership=True))
    for user in forbidden_users:
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 403


@pytest.mark.parametrize(
    "user_factory,assertion",
    [
        pytest.param(
            partial(PrescriberFactory, membership__organization__authorized=False),
            assertNotContains,
            id="PrescriberAloneInOrganization",
        ),
        pytest.param(
            lambda: PrescriberFactory.create_batch(
                2,
                membership__organization=PrescriberOrganizationFactory(with_membership=True),
                membership__is_active=True,
            )[0],
            assertContains,
            id="PrescriberWithActiveMember",
        ),
        pytest.param(
            lambda: PrescriberFactory.create_batch(
                2,
                membership__organization=PrescriberOrganizationFactory(with_membership=True),
                membership__is_active=factory.Iterator([True, False]),
            )[0],
            assertContains,
            id="PrescriberWithOldMember",
        ),
    ],
)
def test_displayed_tabs(client, user_factory, assertion):
    client.force_login(user_factory())
    response = client.get(reverse("job_seekers_views:list"))

    assertion(
        response,
        f"""<a class="nav-link" href="{reverse("job_seekers_views:list_organization")}">
        Tous les accompagnements de la structure</a>""",
        html=True,
    )


@pytest.mark.parametrize(
    "user_factory, url",
    [
        (
            partial(PrescriberFactory, membership=True),
            reverse("job_seekers_views:list"),
        ),
        (
            partial(PrescriberFactory, membership=True),
            reverse("job_seekers_views:list_organization"),
        ),
        (
            partial(EmployerFactory, membership=True, membership__company__subject_to_iae_rules=True),
            reverse("job_seekers_views:list_organization"),
        ),
        (
            partial(EmployerFactory, membership=True, membership__company__not_subject_to_iae_rules=True),
            reverse("job_seekers_views:list_organization"),
        ),
    ],
    ids=[
        "prescriber_assignments_filters",
        "prescriber_organization_assignments_filters",
        "siae_assignments_filters",
        "geiq_or_opcs_assignments_filters",
    ],
)
def test_displayed_top_filters(client, user_factory, url, snapshot):
    user = user_factory()
    client.force_login(user)
    response = client.get(url)
    top_filters = pretty_indented(parse_response_to_soup(response, selector=".btn-dropdown-filter-group"))
    assert top_filters == snapshot


@pytest.mark.parametrize(
    "user_factory",
    [
        partial(PrescriberFactory, membership=True),
        partial(PrescriberFactory, membership=True, membership__organization__authorized=True),
        partial(EmployerFactory, membership=True, membership__company__subject_to_iae_rules=True),
    ],
    ids=[
        "prescriber",
        "authorized_prescriber",
        "iae_employer",
    ],
)
def test_displayed_canvas_filters(client, user_factory, snapshot):
    user = user_factory()
    url = reverse("job_seekers_views:list_organization")
    client.force_login(user)
    response = client.get(url)
    canvas_filters = pretty_indented(parse_response_to_soup(response, selector="#offcanvasApplyFiltersContent"))
    assert canvas_filters == snapshot


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_empty_list(client, url, snapshot):
    organization = PrescriberOrganizationWith2MembershipFactory(not_in_territorial_experimentation=True)
    client.force_login(organization.members.first())
    response = client.get(url)
    assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot


@freeze_time("2024-08-30")
def test_multiple(client, snapshot):
    url = reverse("job_seekers_views:list")

    # App with diagnosis but without approval
    organization = PrescriberOrganizationFactory(for_snapshot=True, authorized=True)
    prescriber = PrescriberMembershipFactory(
        user__first_name="Odile", user__last_name="Deray", organization=organization
    ).user
    other_prescriber = PrescriberMembershipFactory(
        user__first_name="Patrick", user__last_name="Bialès", organization=organization
    ).user
    job_app = JobApplicationFactory(
        job_seeker__first_name="Alain",
        job_seeker__last_name="Zorro",
        job_seeker__public_id="11111111-1111-1111-1111-111111111111",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        job_seeker__jobseeker_profile__is_stalled=True,
        sent_by_authorized_prescriber=True,
        sender=prescriber,
        sender_prescriber_organization=organization,
        updated_at=timezone.now() - datetime.timedelta(days=1),
        with_iae_eligibility_diagnosis=True,
    )
    job_seeker_assignment = JobSeekerAssignmentFactory(
        job_seeker=job_app.job_seeker,
        professional=other_prescriber,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
        last_action_at=timezone.now() - datetime.timedelta(days=1),
    )

    # Other app for the same job seeker
    JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        sender_prescriber_organization=organization,
        job_seeker=job_app.job_seeker,
        updated_at=timezone.now() - datetime.timedelta(days=2),
    )
    JobSeekerAssignmentFactory(
        job_seeker=job_app.job_seeker,
        professional=prescriber,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
        last_action_at=timezone.now() - datetime.timedelta(days=2),
    )
    # Other app without diagnosis
    job_app2 = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        job_seeker__first_name="Bernard",
        job_seeker__last_name="Ygrec",
        job_seeker__public_id="22222222-2222-2222-2222-222222222222",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        job_seeker__jobseeker_profile__is_stalled=True,
        sender_prescriber_organization=organization,
    )
    job_seeker_assignment2 = JobSeekerAssignmentFactory(
        job_seeker=job_app2.job_seeker,
        professional=prescriber,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
    )
    # Other app with approval
    job_app3 = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        job_seeker__first_name="Charlotte",
        job_seeker__last_name="Xerus",
        job_seeker__public_id="33333333-3333-3333-3333-333333333333",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        job_seeker__jobseeker_profile__is_stalled=True,
        job_seeker__jobseeker_profile__is_not_stalled_anymore=True,
        with_approval=True,
        sender_prescriber_organization=organization,
    )
    JobSeekerAssignmentFactory(
        job_seeker=job_app3.job_seeker,
        professional=prescriber,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
        last_action_at=timezone.now() - datetime.timedelta(days=2),
    )

    company = CompanyFactory(for_snapshot=True)
    employer = CompanyMembershipFactory(company=company).user
    job_seeker_assignment3 = JobSeekerAssignmentFactory(
        job_seeker=job_app3.job_seeker,
        professional=employer,
        company=company,
        last_action_kind=ActionKind.ACCEPT,
        assigned_to_unknown_advisor=True,
        last_action_at=timezone.now() - datetime.timedelta(days=1),
    )

    # Other app without address/city
    job_app4 = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        sender_prescriber_organization=organization,
        job_seeker__first_name="David",
        job_seeker__last_name="Waterford",
        job_seeker__public_id="44444444-4444-4444-4444-444444444444",
        with_iae_eligibility_diagnosis=True,
        with_job_seeker_assignment=True,
    )
    # Other app for which the current user cannot see the personal information
    unauthorized_prescriber = PrescriberFactory(membership=True)
    job_app5 = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=unauthorized_prescriber,
        job_seeker__first_name="Edouard",
        job_seeker__last_name="Vivant",
        job_seeker__public_id="55555555-5555-5555-5555-555555555555",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        with_job_seeker_assignment=True,
    )

    client.force_login(prescriber)
    with assertSnapshotQueries(snapshot(name="job seekers list SQL")):
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, selector="table")) == snapshot(
            name="job seekers list table"
        )

        # Address is in search URL
        for i, application in enumerate([job_app, job_app2, job_app3]):
            assert_contains_button_apply_for(response, application.job_seeker, with_city=True)

        for assignment in [job_seeker_assignment, job_seeker_assignment2, job_seeker_assignment3]:
            assert_contains_last_advisor(response, assignment)
            assert_contains_button_advisor_self_assign(
                response, assignment.job_seeker, is_last_advisor=assignment.professional == prescriber
            )

        # Job seeker does not have an address, so it is not in the URL
        assert_contains_button_apply_for(response, job_app4.job_seeker, with_city=False)

    # The links to the eligibility update view are shown
    assert_update_eligibility(response, can_update=True)

    # Current user cannot view personal information, so the city is not in the URL
    client.force_login(unauthorized_prescriber)
    response = client.get(url)
    assert_contains_button_apply_for(response, job_app5.job_seeker, with_city=False, with_personal_information=False)


@override_settings(PAGE_SIZE_LARGE=1)
def test_pagination(client):
    url = reverse("job_seekers_views:list")
    organization = PrescriberOrganizationWith2MembershipFactory(authorized=True)
    prescriber = organization.members.first()
    JobApplicationFactory.create_batch(
        2,
        sent_by_prescriber_alone=True,
        sender=prescriber,
        with_job_seeker_assignment=True,
    )
    client.force_login(prescriber)
    response = client.get(url)
    assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (url + "?page=1"), html=True)


@freeze_time("2024-08-30")
def test_multiple_with_job_seekers_created_by_organization(client, snapshot):
    url_user = reverse("job_seekers_views:list")
    url_organization = reverse("job_seekers_views:list_organization")
    organization = PrescriberOrganizationFactory(for_snapshot=True, authorized=True)
    prescriber = PrescriberMembershipFactory(
        user__first_name="Emile", user__last_name="Gravier", organization=organization
    ).user
    other_prescriber = PrescriberMembershipFactory(
        user__first_name="Jean-Paul", user__last_name="Martoni", organization=organization
    ).user

    # Job seeker created by this prescriber
    alain = JobSeekerFactory(
        first_name="Alain",
        last_name="Zorro",
        public_id="11111111-1111-1111-1111-111111111111",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
    )
    # When applying for a job seeker already in the list, he's not shown twice
    JobApplicationFactory(
        job_seeker=alain,
        sender=prescriber,
        sent_by_authorized_prescriber=True,
        updated_at=timezone.now() - datetime.timedelta(days=1),
        with_iae_eligibility_diagnosis=True,
    )
    alain_assignment = JobSeekerAssignmentFactory(
        job_seeker=alain,
        professional=prescriber,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
        last_action_at=timezone.now() - datetime.timedelta(days=1),
    )

    # Job seeker created by another member of the organization
    bernard = JobSeekerFactory(
        first_name="Bernard",
        last_name="Ygrec",
        public_id="22222222-2222-2222-2222-222222222222",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
    )
    bernard_assignment = JobSeekerAssignmentFactory(
        job_seeker=bernard,
        professional=other_prescriber,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
        assigned_to_unknown_advisor=True,
    )

    # Job seeker created by a member of the organization, but not in the organization anymore
    prescriber_not_in_org_anymore = PrescriberFactory(
        first_name="Simon",
        last_name="Jérémi",
        membership__organization=organization,
        membership__is_active=False,
    )
    charlotte = JobSeekerFactory(
        first_name="Charlotte",
        last_name="Xerus",
        public_id="33333333-3333-3333-3333-333333333333",
        post_code="29200",
        city="Brest",
        created_by=prescriber_not_in_org_anymore,
    )
    JobSeekerAssignmentFactory(
        job_seeker=charlotte,
        professional=prescriber_not_in_org_anymore,
        prescriber_organization=organization,
        last_action_kind=ActionKind.CREATE,
        last_action_at=timezone.now() - datetime.timedelta(days=2 * 365),
    )

    company = CompanyFactory(for_snapshot=True)
    employer = CompanyMembershipFactory(company=company, user__first_name="Serge", user__last_name="Karamazov").user
    charlotte_assignment = JobSeekerAssignmentFactory(
        job_seeker=charlotte,
        professional=employer,
        company=company,
        last_action_kind=ActionKind.ACCEPT,
        assigned_to_unknown_advisor=True,
        last_action_at=timezone.now() - datetime.timedelta(days=2),
    )

    # Job seeker created by the prescriber but for another organization; will not be shown
    other_organization = PrescriberOrganizationFactory()
    david = JobSeekerFactory(
        first_name="David",
        last_name="Waterford",
        public_id="44444444-4444-4444-4444-444444444444",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=other_organization,
    )

    # Job seeker created by someone else, for another organization
    edouard = JobSeekerFactory(
        first_name="Edouard",
        last_name="Vivant",
        public_id="55555555-5555-5555-5555-555555555555",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=other_organization,
    )

    client.force_login(prescriber)
    with assertSnapshotQueries(snapshot(name="job seekers created by organization list with SQL")):
        response = client.get(url_organization)
        soup = parse_response_to_soup(response, selector="tbody")
        assert pretty_indented(soup) == snapshot(name="job seekers list tbody")

        # Job seekers are displayed for the prescriber
        for job_seeker in [alain, bernard, charlotte]:
            assert_contains_job_seeker(response, job_seeker, back_url=url_organization, with_personal_information=True)
            assert_contains_button_apply_for(response, job_seeker, with_city=True)

        for assignment in [alain_assignment, bernard_assignment, charlotte_assignment]:
            assert_contains_last_advisor(response, assignment)
            assert_contains_button_advisor_self_assign(
                response, assignment.job_seeker, is_last_advisor=assignment.professional == prescriber
            )

        # Job seeker not displayed for the prescriber
        for job_seeker in [david, edouard]:
            assertNotContains(response, job_seeker.get_full_name())
            assertNotContains(
                response, reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})
            )

    # The job seekers created by the other member of the organization are not shown in the
    # "Mes candidats" tab
    response = client.get(url_user)

    # Job seekers are displayed for the prescriber
    for job_seeker in [alain]:
        assert_contains_job_seeker(response, job_seeker, back_url=url_user, with_personal_information=True)
        assert_contains_button_apply_for(response, job_seeker, with_city=True)

    # Job seeker not displayed for the prescriber
    for job_seeker in [bernard, charlotte, david, edouard]:
        assertNotContains(response, job_seeker.get_full_name())
        assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}))


def test_job_seeker_created_for_prescription_is_shown(client):
    company = CompanyFactory(with_membership=True, with_jobs=True)
    organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
    company_url = reverse("companies_views:card", kwargs={"company_pk": company.pk})
    prescriber = organization.members.first()
    client.force_login(prescriber)
    client.get(company_url)

    # Init complete session
    apply_session = fake_session_initialization(client, company, None, {})
    session = client.session
    session_name = str(uuid.uuid4())
    session[session_name] = {
        "config": {
            "tunnel": "sender",
            "from_url": reverse("companies_views:card", kwargs={"company_pk": company.pk}),
        },
        "apply": {
            "company_pk": company.pk,
            "session_uuid": apply_session.name,
        },
        "user": {
            "email": "jeandujardin@inclusion.gouv.fr",
            "title": "M",
            "first_name": "Jean",
            "last_name": "Dujardin",
            "lack_of_nir": True,
            "address_line_1": "Moullé",
            "address_line_2": "",
            "post_code": "32150",
            "city": "Cazaubon",
            "ban_api_resolved_address": "Moullé 32150 Cazaubon",
            "phone": "",
            "insee_code": "32096",
            "fill_mode": "ban_api",
            "address_for_autocomplete": "32096_quuf69",
        },
        "profile": {
            "nir": "",
            "birth_country": 91,
            "birth_place": Commune.objects.by_insee_code_and_period("64483", datetime.date(2000, 1, 1)).pk,
            "birthdate": datetime.date(2000, 1, 1),
            "lack_of_nir_reason": "NO_NIR",
            "education_level": "00",
            "resourceless": True,
            "pole_emploi_id": "",
            "pole_emploi_since": "",
            "unemployed_since": "",
            "rqth_employee": False,
            "oeth_employee": False,
            "has_rsa_allocation": "NON",
            "rsa_allocation_since": "",
            "ass_allocation_since": "",
            "aah_allocation_since": "",
            "pole_emploi": False,
            "unemployed": False,
            "rsa_allocation": False,
            "ass_allocation": False,
            "aah_allocation": False,
            "pole_emploi_id_forgotten": "",
            "lack_of_pole_emploi_id_reason": "NOT_REGISTERED",
        },
    }
    session[f"{session_name}_session_kind"] = "job-seeker-get-or-create"
    session.save()

    # Create job seeker step end
    next_url = reverse(
        "job_seekers_views:create_job_seeker_step_end_for_sender", kwargs={"session_uuid": session_name}
    )
    client.post(next_url)
    job_seeker = User.objects.get(kind=UserKind.JOB_SEEKER, email="jeandujardin@inclusion.gouv.fr")

    # Check that job seeker is in list
    response = client.get(reverse("job_seekers_views:list"))
    assert_contains_job_seeker(response, job_seeker, with_personal_information=True)


@freeze_time("2024-08-30")
def test_multiple_with_job_seekers_created_by_unauthorized_organization(client):
    url_user = reverse("job_seekers_views:list")
    url_organization = reverse("job_seekers_views:list_organization")
    organization = PrescriberOrganizationWith2MembershipFactory(authorized=False)
    [prescriber, other_prescriber] = organization.members.all()
    client.force_login(prescriber)

    # Job seeker created by this prescriber
    alain = JobSeekerFactory(
        first_name="Alain",
        last_name="Zorro",
        public_id="11111111-1111-1111-1111-111111111111",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=organization,
    )

    # Job seeker created by another member of the organization
    bernard = JobSeekerFactory(
        first_name="Bernard",
        last_name="Ygrec",
        public_id="22222222-2222-2222-2222-222222222222",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=organization,
    )

    response = client.get(url_user)
    # A job seeker created by the user is shown with personal information
    assert_contains_job_seeker(response, alain, back_url=url_user, with_personal_information=True)
    assert_contains_button_apply_for(response, alain, with_city=True)
    # A job seeker created by a member of the unauthorized organization isn't shown
    assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": bernard.public_id}))

    response = client.get(url_organization)
    # A job seeker created by the user is shown with personal information
    assert_contains_job_seeker(response, alain, back_url=url_organization, with_personal_information=True)
    assert_contains_button_apply_for(response, alain, with_city=True)
    # A job seeker created by a member of the unauthorized organization is shown *without* personal information
    assert_contains_job_seeker(response, bernard, back_url=url_organization, with_personal_information=False)
    assert_contains_button_apply_for(response, bernard, with_city=False, with_personal_information=False)

    # There's no link to the eligibility update view
    assert_update_eligibility(response, can_update=False)


def test_job_seeker_created_by_prescriber_without_org(client):
    """
    Check that a job seeker created by an "orienteur solo" is not shared among
    all the "orienteurs solo"
    """
    prescriber = PrescriberFactory(membership=True)
    other_prescriber = ProfessionalFactory()
    organization = PrescriberOrganizationFactory()

    # Job seeker created by another prescriber
    alain = JobSeekerFactory(
        first_name="Alain",
        last_name="Zorro",
        public_id="11111111-1111-1111-1111-111111111111",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
        with_job_seeker_assignment=True,
    )
    # Job seeker created by this prescriber
    bernard = JobSeekerFactory(
        first_name="Bernard",
        last_name="Ygrec",
        public_id="22222222-2222-2222-2222-222222222222",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        with_job_seeker_assignment=True,
    )
    # Job seeker created by this prescriber when he was in an organization.
    # He is not member of it anymore, it won't be shown anymore
    charlotte = JobSeekerFactory(
        first_name="Charlotte",
        last_name="Xerus",
        public_id="33333333-3333-3333-3333-333333333333",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=organization,
    )

    # The prescriber is now in another org (without it they can't use the website)
    client.force_login(prescriber)
    response = client.get(reverse("job_seekers_views:list"))
    assertNotContains(response, alain.get_full_name())
    assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": alain.public_id}))

    assert_contains_job_seeker(response, bernard, with_personal_information=True)
    assert_contains_button_apply_for(response, bernard, with_city=True)

    assertNotContains(response, charlotte.get_full_name())
    assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": charlotte.public_id}))

    # There's no link to the eligibility update view
    assert_update_eligibility(response, can_update=False)


@pytest.mark.parametrize(
    "factory, url",
    [
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list")),
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list_organization")),
        (CompanyWith2MembershipsFactory, reverse("job_seekers_views:list_organization")),
    ],
    ids=["prescriber_assignments_list", "prescriber_organization_assignments_list", "employer_assignments_list"],
)
def test_htmx_job_seeker_filter(client, factory, url):
    organization = factory()
    user = organization.members.first()
    is_prescriber_organization = isinstance(organization, PrescriberOrganization)
    is_company = isinstance(organization, Company)
    job_app_factory = partial(
        JobApplicationFactory,
        sent_by_prescriber=is_prescriber_organization,
        sender_prescriber_organization=(is_prescriber_organization and organization or None),
        sent_by_employer=is_company,
        sender_company=(is_company and organization or None),
    )
    job_app = job_app_factory(
        sender=user,
        with_job_seeker_assignment=True,
    )
    other_app = job_app_factory(
        sender=user,
        with_job_seeker_assignment=True,
    )
    client.force_login(user)
    response = client.get(url)

    assertContains(response, "2 résultats")
    assertContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id}))
    assertContains(
        response, reverse("job_seekers_views:details", kwargs={"public_id": other_app.job_seeker.public_id})
    )
    simulated_page = parse_response_to_soup(response)

    # Filter by job_app.job_seeker_id
    [job_seeker_select] = simulated_page.find_all("select", {"id": "id_job_seeker"})
    for option in job_seeker_select.find_all("option"):
        if option["value"] == "":
            del option["selected"]
        if option["value"] == str(job_app.job_seeker_id):
            option["selected"] = ""
    response = client.get(url, {"job_seeker": job_app.job_seeker_id}, headers={"HX-Request": "true"})
    update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
    response = client.get(url, {"job_seeker": job_app.job_seeker_id})
    assertContains(response, "1 résultat")
    fresh_page = parse_response_to_soup(response)
    assertSoupEqual(simulated_page, fresh_page)


def test_filtered_by_job_seeker_for_unauthorized_prescriber(client):
    prescriber = PrescriberOrganizationWith2MembershipFactory().members.first()
    a_b_job_seeker = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        job_seeker__first_name="A_something",
        job_seeker__last_name="B_something",
        with_job_seeker_assignment=True,
    ).job_seeker
    created_job_seeker = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="Zorro",
        job_seeker__last_name="Martin",
        with_job_seeker_assignment=True,
    ).job_seeker
    c_d_job_seeker = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__last_login=timezone.now(),
        job_seeker__first_name="Catherine",
        job_seeker__last_name="Dupont",
        with_job_seeker_assignment=True,
    ).job_seeker
    client.force_login(prescriber)

    url = reverse("job_seekers_views:list")
    response = client.get(url, {"job_seeker": created_job_seeker.pk})
    job_seekers = response.context["page_obj"].object_list
    assert len(job_seekers) == 1
    assert job_seekers[0].pk == created_job_seeker.pk

    response = client.get(url)
    job_seekers = response.context["page_obj"].object_list
    assert len(job_seekers) == 3
    filters_form = response.context["filters_form"]
    assert filters_form.fields["job_seeker"].choices == [
        (a_b_job_seeker.pk, "B… A…"),
        (c_d_job_seeker.pk, "DUPONT Catherine"),
        (created_job_seeker.pk, "MARTIN Zorro"),
    ]


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_filtered_by_eligibility_state(client, url):
    """
    Éligibilité "IAE valide": show job seekers with valid diagnosis OR with valid approval.
    Éligibilité "IAE à valider": show job seekers without valid diagnosis AND without valid approval.
    """
    organization = PrescriberOrganizationWith2MembershipFactory()
    prescriber = organization.members.first()
    client.force_login(prescriber)
    # Eligibility validated
    job_seeker_valid_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        job_seeker__first_name="valid eligibility, no approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker
    job_seeker_valid_geiq_eligibility_no_approval = GEIQEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        job_seeker__first_name="valid geiq eligibility, no approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker
    job_seeker_expired_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        expired=True,
        # assignment.last_action_at is set to diagnosis created_at, which is flaky when expired=True
        created_at=timezone.now() - datetime.timedelta(days=2),
        job_seeker__first_name="expired eligibility, valid approval",
        job_seeker__last_name="Zorro",
        # assignment.last_action_at is one day earlier as expired=True changes created_at
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_valid_approval)
    job_seeker_valid_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        job_seeker__first_name="valid eligibility, valid approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(user=job_seeker_valid_eligibility_valid_approval)

    # Eligibility to validate
    job_seeker_expired_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        expired=True,
        # assignment.last_action_at is set to diagnosis created_at, which is non-deterministic when expired=True
        created_at=timezone.now() - datetime.timedelta(days=1),
        job_seeker__first_name="expired eligibility, no approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker

    response = client.get(url, {"eligibility_validated": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_valid_eligibility_valid_approval,
        job_seeker_valid_eligibility_no_approval,
        job_seeker_expired_eligibility_valid_approval,
    ]

    response = client.get(url, {"eligibility_pending": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_valid_geiq_eligibility_no_approval,
        job_seeker_expired_eligibility_no_approval,
    ]

    response = client.get(url, {"eligibility_validated": "on", "eligibility_pending": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_valid_eligibility_valid_approval,
        job_seeker_valid_geiq_eligibility_no_approval,
        job_seeker_valid_eligibility_no_approval,
        job_seeker_expired_eligibility_no_approval,
        job_seeker_expired_eligibility_valid_approval,
    ]


@pytest.mark.parametrize(
    "factory, url",
    [
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list")),
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list_organization")),
        (
            partial(CompanyWith2MembershipsFactory, subject_to_iae_rules=True),
            reverse("job_seekers_views:list_organization"),
        ),
    ],
    ids=["prescriber_assignments_list", "prescriber_organization_assignments_list", "siae_assignments_list"],
)
def test_filtered_by_approval_state(client, factory, url):
    organization = factory()
    user = organization.members.first()
    is_prescriber_organization = isinstance(organization, PrescriberOrganization)
    is_company = isinstance(organization, Company)
    prescriber_organization = is_prescriber_organization and organization or None
    company = is_company and organization or None
    client.force_login(user)

    job_seeker_expired_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=is_prescriber_organization,
        from_employer=is_company,
        author=user,
        author_prescriber_organization=prescriber_organization,
        author_siae=company,
        expired=True,
        # assignment.last_action_at is set to diagnosis created_at, which is non-deterministic when expired=True
        created_at=timezone.now() - datetime.timedelta(days=2),
        job_seeker__first_name="expired eligibility, valid approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_valid_approval)

    job_seeker_expired_eligibility_expired_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=is_prescriber_organization,
        from_employer=is_company,
        author=user,
        author_prescriber_organization=prescriber_organization,
        author_siae=company,
        expired=True,
        # assignment.last_action_at is set to diagnosis created_at, which is non-deterministic when expired=True
        created_at=timezone.now() - datetime.timedelta(days=1),
        job_seeker__first_name="expired eligibility, expired approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_expired_approval, expired=True)

    job_seeker_valid_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=is_prescriber_organization,
        from_employer=is_company,
        author=user,
        author_prescriber_organization=prescriber_organization,
        author_siae=company,
        job_seeker__first_name="valid eligibility, no approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker

    response = client.get(url, {"approval_active": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_expired_eligibility_valid_approval]

    response = client.get(url, {"approval_expired": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_expired_eligibility_expired_approval]

    response = client.get(url, {"no_approval": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_valid_eligibility_no_approval]

    response = client.get(url, {"approval_expired": "on", "no_approval": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_valid_eligibility_no_approval,
        job_seeker_expired_eligibility_expired_approval,
    ]

    response = client.get(url, {"approval_active": "on", "approval_expired": "on", "no_approval": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_valid_eligibility_no_approval,
        job_seeker_expired_eligibility_expired_approval,
        job_seeker_expired_eligibility_valid_approval,
    ]


def test_iae_filters_as_non_iae_actor(client, subtests):
    company = CompanyFactory(not_subject_to_iae_rules=True)
    user = EmployerFactory(membership=True, membership__company=company)

    # Eligibility and approval both expired
    job_seeker_expired_eligibility_expired_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        expired=True,
        job_seeker__first_name="expired eligibility, expired approval",
        job_seeker__last_name="Zorro",
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_expired_approval, expired=True)

    # Eligibility validated
    job_seeker_valid_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__first_name="valid eligibility, no approval",
        job_seeker__last_name="Zorro",
    ).job_seeker

    # Eligibility to validate
    job_seeker_expired_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        expired=True,
        job_seeker__first_name="expired eligibility, no approval",
        job_seeker__last_name="Zorro",
    ).job_seeker

    # Eligibility expired and valid approval
    job_seeker_expired_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        expired=True,
        job_seeker__first_name="expired eligibility, valid approval",
        job_seeker__last_name="Zorro",
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_valid_approval)

    # Valid eligibility and valid approval
    job_seeker_valid_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__first_name="valid eligibility, valid approval",
        job_seeker__last_name="Zorro",
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(user=job_seeker_valid_eligibility_valid_approval)

    job_seekers = [
        job_seeker_expired_eligibility_expired_approval,
        job_seeker_valid_eligibility_no_approval,
        job_seeker_expired_eligibility_no_approval,
        job_seeker_expired_eligibility_valid_approval,
        job_seeker_valid_eligibility_valid_approval,
    ]

    for job_seeker in reversed(job_seekers):
        JobSeekerAssignmentFactory(professional=user, company=company, job_seeker=job_seeker)

    url = reverse("job_seekers_views:list_organization")
    iae_filters = {
        "eligibility pending": {"eligibility_pending": "on"},
        "eligibility validated": {"eligibility_validated": "on"},
        "approval active": {"approval_active": "on"},
        "approval expired": {"approval_expired": "on"},
        "no approval": {"no_approval": "on"},
        "approval expired or no approval": {"approval_expired": "on", "no_approval": "on"},
    }
    client.force_login(user)

    for label, iae_filter in iae_filters.items():
        with subtests.test(filters=label):
            response = client.get(url, iae_filter)
            assert response.context["page_obj"].object_list == job_seekers


@freeze_time("2026-01-15")
@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_filtered_by_end_of_iae_journey(client, url, snapshot):
    organization = PrescriberOrganizationFactory(with_membership=True, authorized=True)
    authorized_prescriber = organization.members.first()
    client.force_login(authorized_prescriber)

    today = timezone.localdate()

    def add_soon_ending_approval(job_seeker):
        ApprovalFactory(
            user=job_seeker,
            start_at=today - datetime.timedelta(days=600),
            end_at=today + datetime.timedelta(days=30),
        )

    def add_soon_ending_contract(job_seeker):
        ContractFactory(
            job_seeker=job_seeker,
            start_date=today - datetime.timedelta(days=200),
            end_date=today + datetime.timedelta(days=20),
        )

    # Only a PASS IAE ending soon.
    job_seeker_pass_only = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    add_soon_ending_approval(job_seeker_pass_only)

    # Only an IAE contract ending soon.
    job_seeker_contract_only = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    add_soon_ending_contract(job_seeker_contract_only)

    # Both a PASS IAE and an IAE contract ending soon.
    job_seeker_both = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    add_soon_ending_approval(job_seeker_both)
    add_soon_ending_contract(job_seeker_both)

    # Neither ends soon.
    job_seeker_neither = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    ApprovalFactory(
        user=job_seeker_neither,
        start_at=today - datetime.timedelta(days=100),
        end_at=today + datetime.timedelta(days=91),
    )
    ContractFactory(
        job_seeker=job_seeker_neither,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=31),
    )

    response = client.get(url, {"approval_ending_soon": "on"})
    assert set(response.context["page_obj"].object_list) == {job_seeker_pass_only, job_seeker_both}

    response = client.get(url, {"contract_ending_soon": "on"})
    assert set(response.context["page_obj"].object_list) == {job_seeker_contract_only, job_seeker_both}

    # Both checked => AND: only the job seeker with both a soon PASS and a soon contract.
    response = client.get(url, {"approval_ending_soon": "on", "contract_ending_soon": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_both]

    # Check queries
    with assertSnapshotQueries(snapshot):
        client.get(url, {"approval_ending_soon": "on", "contract_ending_soon": "on"})


@freeze_time("2026-01-15")
def test_end_of_iae_journey_filter_edge_cases(client):
    organization = PrescriberOrganizationFactory(with_membership=True, authorized=True)
    authorized_prescriber = organization.members.first()
    client.force_login(authorized_prescriber)
    url = reverse("job_seekers_views:list")

    today = datetime.date(2026, 1, 15)

    # PASS ending exactly on the 90-day boundary is included (range is inclusive).
    job_seeker_pass_boundary = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    ApprovalFactory(
        user=job_seeker_pass_boundary,
        start_at=today - datetime.timedelta(days=600),
        end_at=today + datetime.timedelta(days=90),
    )

    # Contract ending exactly on the 30-day boundary is included.
    job_seeker_contract_boundary = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    ContractFactory(
        job_seeker=job_seeker_contract_boundary,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=30),
    )

    # A contract without an end date (ongoing) is ignored.
    job_seeker_contract_no_end = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    ContractFactory(
        job_seeker=job_seeker_contract_no_end,
        start_date=today - datetime.timedelta(days=100),
        end_date=None,
    )

    # Several contracts: only the latest end date counts (an older one already ended).
    job_seeker_multiple_contracts = JobSeekerAssignmentFactory(professional=authorized_prescriber).job_seeker
    ContractFactory(
        job_seeker=job_seeker_multiple_contracts,
        start_date=today - datetime.timedelta(days=400),
        end_date=today - datetime.timedelta(days=200),
    )
    ContractFactory(
        job_seeker=job_seeker_multiple_contracts,
        start_date=today - datetime.timedelta(days=100),
        end_date=today + datetime.timedelta(days=15),
    )

    response = client.get(url, {"approval_ending_soon": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_pass_boundary]

    response = client.get(url, {"contract_ending_soon": "on"})
    assert set(response.context["page_obj"].object_list) == {
        job_seeker_contract_boundary,
        job_seeker_multiple_contracts,
    }


@freeze_time("2026-01-15")
def test_end_of_iae_journey_filter_only_for_authorized_prescriber(client):
    # A non-authorized prescriber neither sees the filter nor is affected by its query params.
    organization = PrescriberOrganizationFactory(with_membership=True)
    prescriber = organization.members.first()
    client.force_login(prescriber)
    url = reverse("job_seekers_views:list")

    today = datetime.date(2026, 1, 15)
    job_seeker = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        with_job_seeker_assignment=True,
    ).job_seeker
    # PASS ending far in the future: it would be filtered out if the filter applied.
    ApprovalFactory(
        user=job_seeker,
        start_at=today - datetime.timedelta(days=100),
        end_at=today + datetime.timedelta(days=200),
    )

    assertNotContains(client.get(url), "Fin de parcours IAE à venir")

    response = client.get(url, {"approval_ending_soon": "on", "contract_ending_soon": "on"})
    assert response.context["page_obj"].object_list == [job_seeker]


@freeze_time("2026-01-15")
def test_end_of_iae_journey_filter_for_siae(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    employer = membership.user
    client.force_login(employer)
    url = reverse("job_seekers_views:list_organization")
    today = datetime.date(2026, 1, 15)

    # The filter is now available for an IAE SIAE, like for authorized prescribers.
    response = client.get(url)
    assertContains(response, "Fin de parcours IAE à venir")
    assertContains(response, "Contrat IAE bientôt terminé")

    # A contract ending soon WITH this SIAE is in the cohort.
    job_seeker_own = JobSeekerAssignmentFactory(professional=employer, company=company).job_seeker
    ContractFactory(
        job_seeker=job_seeker_own,
        company=company,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=20),
    )
    # A contract ending soon WITH ANOTHER SIAE must be ignored (scoping avoids the false positive).
    job_seeker_other_company = JobSeekerAssignmentFactory(professional=employer, company=company).job_seeker
    ContractFactory(
        job_seeker=job_seeker_other_company,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=20),
    )

    response = client.get(url, {"contract_ending_soon": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_own]


@freeze_time("2026-01-15")
def test_end_of_contracts_banners_for_siae(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    employer = membership.user
    client.force_login(employer)
    url = reverse("job_seekers_views:list_organization")
    today = datetime.date(2026, 1, 15)

    # No contract ending soon: neither banner.
    response = client.get(url)
    assertNotContains(response, "Afficher ce salarié")
    assertNotContains(response, "Afficher ces salariés")
    assertNotContains(response, "Suggérer une suite de parcours aux salariés")

    # A job seeker with a contract ending soon: discovery banner on the unfiltered list.
    job_seeker = JobSeekerAssignmentFactory(professional=employer, company=company).job_seeker
    ContractFactory(
        job_seeker=job_seeker,
        company=company,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=20),
    )
    response = client.get(url)
    assertContains(response, "Vous avez 1 salarié en fin de contrat")
    assertContains(response, "Afficher ce salarié")
    assertNotContains(response, "Suggérer une suite de parcours aux salariés")

    # When the end-of-journey filter is active: pedagogic banner replaces the discovery banner.
    response = client.get(url, {"contract_ending_soon": "on"})
    assertContains(response, "Suggérer une suite de parcours aux salariés")
    assertNotContains(response, "Afficher ce salariés")
    assertNotContains(response, "Afficher ces salariés")


@freeze_time("2026-01-15")
@override_settings(TALLY_URL="https://tally.example", TALLY_SUGGEST_NEXT_STEP_FORM_ID="wSUGGEST")
def test_suggest_next_step_action_in_list(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    employer = membership.user
    client.force_login(employer)
    url = reverse("job_seekers_views:list_organization")
    today = datetime.date(2026, 1, 15)
    ending_soon = JobSeekerAssignmentFactory(professional=employer, company=company).job_seeker
    ContractFactory(
        job_seeker=ending_soon,
        company=company,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=20),
    )
    # A job seeker with no contract ending soon: no action on their row.
    JobSeekerAssignmentFactory(professional=employer, company=company)

    # Unfiltered: the action is offered on the row of the job seeker ending soon (mirroring the card banner),
    # exactly once, and it links to the Tally form pre-filled with the responding employer's identifiers.
    tally_url = f"https://tally.example/r/wSUGGEST?iduser={employer.pk}&kindcompany={company.kind}"
    response = client.get(url)
    assertContains(response, "Suggérer une suite de parcours")
    assertContains(response, tally_url, count=1)

    # With the end-of-journey filter active, only the job seeker ending soon remains, still with the action.
    response = client.get(url, {"contract_ending_soon": "on"})
    assertContains(response, tally_url, count=1)


@freeze_time("2026-01-15")
@override_settings(TALLY_URL="https://tally.example", TALLY_SUGGEST_NEXT_STEP_FORM_ID="wSUGGEST")
def test_suggest_next_step_banner_on_job_seeker_card(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    employer = membership.user
    client.force_login(employer)
    today = datetime.date(2026, 1, 15)
    job_seeker = JobSeekerAssignmentFactory(professional=employer, company=company).job_seeker
    ContractFactory(
        job_seeker=job_seeker,
        company=company,
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=20),
    )

    response = client.get(reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}))
    assertContains(response, "Le contrat arrive bientôt à échéance")
    assertContains(response, "04/02/2026")
    assertContains(response, f"https://tally.example/r/wSUGGEST?iduser={employer.pk}&kindcompany={company.kind}")


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_suspended_approval_info_tooltip(client, url):
    organization = PrescriberOrganizationWith2MembershipFactory()
    prescriber = organization.members.first()
    client.force_login(prescriber)

    job_seeker = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=prescriber,
        author_prescriber_organization=organization,
        with_job_seeker_assignment=True,
    ).job_seeker
    approval = ApprovalFactory(user=job_seeker)
    SuspensionFactory(approval=approval)

    assertContains(client.get(url), SUSPENDED_APPROVAL_PRESCRIBER_TOOLTIP_MARKUP, html=True)


def test_filtered_by_is_stalled(client):
    prescriber = PrescriberMembershipFactory().user
    client.force_login(prescriber)
    stalled = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        created_at=timezone.now() - datetime.timedelta(days=90),
        sender=prescriber,
        job_seeker__jobseeker_profile__is_stalled=True,
        with_job_seeker_assignment=True,
    )
    not_stalled_anymore = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        created_at=timezone.now() - datetime.timedelta(days=90),
        sender=prescriber,
        job_seeker__jobseeker_profile__is_stalled=True,
        job_seeker__jobseeker_profile__is_not_stalled_anymore=True,
        with_job_seeker_assignment=True,
    )
    other = JobApplicationFactory(sent_by_prescriber_alone=True, sender=prescriber, with_job_seeker_assignment=True)
    response = client.get(reverse("job_seekers_views:list"))
    assert Counter(response.context["page_obj"].object_list) == Counter(
        [stalled.job_seeker, not_stalled_anymore.job_seeker, other.job_seeker]
    )
    response = client.get(reverse("job_seekers_views:list"), {"is_stalled": "on"})
    assert response.context["page_obj"].object_list == [stalled.job_seeker]


@pytest.mark.parametrize(
    "org_factory,membership_factory",
    [
        (
            PrescriberOrganizationWith2MembershipFactory,
            lambda org: partial(PrescriberMembershipFactory, organization=org),
        ),
        (
            CompanyWith2MembershipsFactory,
            lambda org: partial(CompanyMembershipFactory, company=org),
        ),
    ],
    ids=["filtered_by_prescribers", "filtered_by_employers"],
)
def test_filtered_by_organization_members(client, org_factory, membership_factory):
    organization = org_factory(membership1__user__first_name="Alice", membership2__user__first_name="Billy")
    is_prescriber_organization = isinstance(organization, PrescriberOrganization)
    is_company = isinstance(organization, Company)
    professional = organization.members.first()
    member = organization.members.last()
    old_member = membership_factory(organization)(user__is_active=False, user__first_name="Charlie").user
    other_pro_not_in_orga = ProfessionalFactory(first_name="Deborah")
    prescriber_organization = is_prescriber_organization and organization or None
    company = is_company and organization or None

    job_seeker_assigned_to_professional = JobSeekerAssignmentFactory(
        professional=professional,
        prescriber_organization=prescriber_organization,
        company=company,
    ).job_seeker

    job_seeker_assigned_to_member = JobSeekerAssignmentFactory(
        professional=member,
        prescriber_organization=prescriber_organization,
        company=company,
    ).job_seeker

    job_seeker_assigned_to_old_member = JobSeekerAssignmentFactory(
        professional=old_member,
        prescriber_organization=prescriber_organization,
        company=company,
    ).job_seeker

    JobSeekerAssignmentFactory(
        job_seeker=job_seeker_assigned_to_professional,
        professional=other_pro_not_in_orga,
    )

    client.force_login(professional)

    url = reverse("job_seekers_views:list_organization")
    response = client.get(url)
    assert response.context["page_obj"].object_list == [
        job_seeker_assigned_to_old_member,
        job_seeker_assigned_to_member,
        job_seeker_assigned_to_professional,
    ]

    for organization_member in [professional, member, old_member]:
        assertContains(response, organization_member.get_full_name())
    assertNotContains(response, other_pro_not_in_orga.get_full_name())

    response = client.get(url, {"organization_members": member.pk})
    assert response.context["page_obj"].object_list == [job_seeker_assigned_to_member]

    response = client.get(url, {"organization_members": old_member.pk})
    assert response.context["page_obj"].object_list == [job_seeker_assigned_to_old_member]


@pytest.mark.parametrize(
    "factory, url",
    [
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list")),
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list_organization")),
        (
            partial(CompanyWith2MembershipsFactory, subject_to_iae_rules=True),
            reverse("job_seekers_views:list_organization"),
        ),
        (
            partial(CompanyWith2MembershipsFactory, not_subject_to_iae_rules=True),
            reverse("job_seekers_views:list_organization"),
        ),
    ],
    ids=[
        "prescriber_assignments_list",
        "prescriber_organization_assignments_list",
        "siae_assignments_list",
        "geiq_or_opcs_assignments_list",
    ],
)
def test_htmx_filters(client, factory, url):
    organization = factory()
    is_prescriber_organization = isinstance(organization, PrescriberOrganization)
    is_company = isinstance(organization, Company)
    user = organization.members.first()
    client.force_login(user)

    IAEEligibilityDiagnosisFactory(
        from_prescriber=is_prescriber_organization,
        from_employer=is_company,
        job_seeker__created_by=user,
        with_job_seeker_assignment=True,
    )
    response = client.get(url)
    page = parse_response_to_soup(response, selector="#main")
    # Simulate the data-emplois-sync-with and check both checkboxes.
    eligibility_validated_checkboxes = page.find_all("input", attrs={"name": "eligibility_validated"})
    if isinstance(organization, PrescriberOrganization) or organization.is_subject_to_iae_rules:
        assert len(eligibility_validated_checkboxes) == 2
        for checkbox in eligibility_validated_checkboxes:
            checkbox["checked"] = ""
    else:
        assert len(eligibility_validated_checkboxes) == 0

    response = client.get(url, {"eligibility_validated": "on"}, headers={"HX-Request": "true"})
    update_page_with_htmx(page, f"form[hx-get='{url}']", response)

    response = client.get(url, {"eligibility_validated": "on"})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)


@pytest.mark.parametrize(
    "factory, url",
    [
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list")),
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list_organization")),
        (CompanyWith2MembershipsFactory, reverse("job_seekers_views:list_organization")),
    ],
    ids=["prescriber_assignments_list", "prescriber_organization_assignments_list", "employer_assignments_list"],
)
def test_job_seekers_order(client, factory, url, subtests):
    organization = factory()
    user = organization.members.first()
    is_prescriber_organization = isinstance(organization, PrescriberOrganization)
    is_company = isinstance(organization, Company)
    prescriber_organization = is_prescriber_organization and organization or None
    company = is_company and organization or None
    c_d_job_seeker = JobApplicationFactory(
        sent_by_prescriber_alone=is_prescriber_organization,
        sent_by_employer=is_company,
        sender=user,
        sender_company=company,
        job_seeker__created_by=user,
        job_seeker__first_name="Charles",
        job_seeker__last_name="Deux candidatures",
    ).job_seeker
    JobApplicationFactory(
        sent_by_prescriber_alone=is_prescriber_organization,
        sent_by_employer=is_company,
        sender=user,
        sender_company=company,
        job_seeker=c_d_job_seeker,
        with_job_seeker_assignment=True,
    )
    created_job_seeker = JobSeekerFactory(
        created_by=user,
        first_name="Zorro",
        last_name="Martin",
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=prescriber_organization,
    )
    if is_company:
        JobSeekerAssignmentFactory(
            job_seeker=created_job_seeker,
            professional=user,
            company=company,
        )
    second_created_job_seeker = JobSeekerFactory(
        created_by=user,
        first_name="Zorro",
        last_name="Martin",
        with_job_seeker_assignment=True,
        with_job_seeker_assignment__prescriber_organization=prescriber_organization,
    )
    if is_company:
        JobSeekerAssignmentFactory(
            job_seeker=second_created_job_seeker,
            professional=user,
            company=company,
        )
    a_b_job_seeker = JobApplicationFactory(
        sent_by_prescriber_alone=is_prescriber_organization,
        sent_by_employer=is_company,
        sender_company=company,
        sender=user,
        job_seeker__first_name="Alice",
        job_seeker__last_name="Berger",
        with_job_seeker_assignment=True,
    ).job_seeker
    # Simulate IAE eligibility diagnosis done by prescriber
    JobSeekerAssignment.objects.upsert_assignment(
        job_seeker=second_created_job_seeker,
        professional=user,
        organization=organization,
        last_action_kind=ActionKind.IAE_ELIGIBILITY,
    )

    client.force_login(user)

    expected_order = {
        "-last_action_at": [second_created_job_seeker, a_b_job_seeker, created_job_seeker, c_d_job_seeker],
        "full_name": [a_b_job_seeker, c_d_job_seeker, created_job_seeker, second_created_job_seeker],
        "job_applications_nb": [created_job_seeker, second_created_job_seeker, a_b_job_seeker, c_d_job_seeker],
    }

    with subtests.test(order="<missing_value>"):
        response = client.get(url)
        assert response.context["page_obj"].object_list == expected_order["-last_action_at"]

    with subtests.test(order="<invalid_value>"):
        response = client.get(url, {"order": "invalid_value"})
        assert response.context["page_obj"].object_list == expected_order["-last_action_at"]

    for order, job_seekers in expected_order.items():
        with subtests.test(order=order):
            response = client.get(url, {"order": order})
            assert response.context["page_obj"].object_list == job_seekers

            inverse_order = order[1:] if order[0] == "-" else f"-{order}"
            response = client.get(url, {"order": inverse_order})
            assert response.context["page_obj"].object_list == list(reversed(job_seekers))


@pytest.mark.parametrize(
    "factory, url",
    [
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list")),
        (PrescriberOrganizationWith2MembershipFactory, reverse("job_seekers_views:list_organization")),
        (CompanyWith2MembershipsFactory, reverse("job_seekers_views:list_organization")),
    ],
    ids=["prescriber_assignments_list", "prescriber_organization_assignments_list", "employer_assignments_list"],
)
def test_htmx_order(client, factory, url):
    organization = factory()
    user = organization.members.first()
    is_prescriber_organization = isinstance(organization, PrescriberOrganization)
    is_company = isinstance(organization, Company)
    job_app_factory = partial(
        JobApplicationFactory,
        sent_by_prescriber=is_prescriber_organization,
        sender_prescriber_organization=(is_prescriber_organization and organization or None),
        sent_by_employer=is_company,
        sender_company=(is_company and organization or None),
    )
    job_app = job_app_factory(
        sender=user,
        with_job_seeker_assignment=True,
    )
    other_app = job_app_factory(
        sender=user,
        with_job_seeker_assignment=True,
    )
    client.force_login(user)
    response = client.get(url)

    assertContains(response, "2 résultats")
    assertContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id}))
    assertContains(
        response, reverse("job_seekers_views:details", kwargs={"public_id": other_app.job_seeker.public_id})
    )
    simulated_page = parse_response_to_soup(response)

    ORDER_ID = "id_order"
    LAST_ACTION_AT_ASC = "last_action_at"

    [sort_by_last_action_at_button] = simulated_page.find_all(
        "button", {"data-emplois-setter-value": LAST_ACTION_AT_ASC}
    )
    assert sort_by_last_action_at_button["data-emplois-setter-target"] == f"#{ORDER_ID}"
    [order_input] = simulated_page.find_all(id=ORDER_ID)
    # Simulate click on button
    order_input["value"] = LAST_ACTION_AT_ASC
    response = client.get(url, {"order": LAST_ACTION_AT_ASC}, headers={"HX-Request": "true"})
    update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
    response = client.get(url, {"order": LAST_ACTION_AT_ASC})
    assertContains(response, "2 résultats")
    assertContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id}))
    assertContains(
        response, reverse("job_seekers_views:details", kwargs={"public_id": other_app.job_seeker.public_id})
    )
    fresh_page = parse_response_to_soup(response)
    assertSoupEqual(simulated_page, fresh_page)


@freeze_time("2026-06-11")
def test_last_action_at(client):
    organization = PrescriberOrganizationWith2MembershipFactory()
    prescriber = organization.members.first()
    job_seeker = JobSeekerFactory()
    now = timezone.now()
    ten_days_ago = now - datetime.timedelta(days=10)
    thirty_days_ago = now - datetime.timedelta(days=30)
    _assignment_no_org = JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
        professional=prescriber,
        last_action_at=ten_days_ago,
    )
    assignment_with_org = JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
        professional=prescriber,
        prescriber_organization=organization,
        last_action_at=thirty_days_ago,
    )

    client.force_login(prescriber)
    url = reverse("job_seekers_views:list")

    response = client.get(url)
    assertContains(response, ten_days_ago.strftime("%d/%m/%Y"))

    assignment_with_org.last_action_at = now
    assignment_with_org.save()
    assignment_with_org.refresh_from_db()

    response = client.get(url)
    assertContains(response, now.strftime("%d/%m/%Y"))


ACCOMPANIMENT_REVIEW_ACTION_LABEL = ""


@freeze_time("2026-01-15")
@pytest.mark.parametrize("view", ("job_seekers_views:list", "job_seekers_views:list_organization"))
def test_pro_support_request_action_for_authorized_prescriber(client, view):
    organization = PrescriberOrganizationFactory(with_membership=True, authorized=True)
    user = organization.members.first()
    client.force_login(user)
    today = datetime.date(2026, 1, 15)

    job_seeker = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=user,
        author_prescriber_organization=organization,
        job_seeker__first_name="Jean",
        job_seeker__last_name="Dupont",
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(
        user=job_seeker,
        start_at=today - datetime.timedelta(days=600),
        end_at=today + datetime.timedelta(days=30),
    )
    job_application = JobApplicationFactory(
        job_seeker=job_seeker,
        sent_by_job_seeker=True,
        to_company__email="",
        state=JobApplicationState.ACCEPTED,
        hiring_start_at=today - datetime.timedelta(days=200),
    )

    # Without the end-of-journey filter, the action is hidden.
    mailto_label = "Demander un bilan d’accompagnement à la SIAE"
    url = reverse(view)
    response = client.get(url)
    assertNotContains(response, mailto_label)

    # With the filter active, the action should be displayed, unless
    # the company does not have any email.
    response = client.get(url, {"approval_ending_soon": "on"})
    assertNotContains(response, mailto_label)

    # Now with a company that has an e-mail.
    company = job_application.to_company
    company.email = "siae@example.com"
    company.save()
    response = client.get(url, {"approval_ending_soon": "on"})
    assertContains(response, mailto_label)
    assertContains(response, "mailto:siae@example.com?subject=Demande%20de%20bilan%20d%E2%80%99accompagnement")
    assertContains(response, "Jean%20DUPONT%20arrive")


@freeze_time("2026-01-15")
def test_pro_support_request_not_for_employer(client):
    company = CompanyFactory(subject_to_iae_rules=True, email="siae@example.com")
    employer = CompanyMembershipFactory(company=company).user
    client.force_login(employer)
    url = reverse("job_seekers_views:list_organization")
    today = datetime.date(2026, 1, 15)

    job_seeker = JobSeekerFactory()
    JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
        professional=employer,
        company=company,
    )
    ApprovalFactory(
        user=job_seeker,
        start_at=today - datetime.timedelta(days=600),
        end_at=today + datetime.timedelta(days=30),
    )
    JobApplicationFactory(
        job_seeker=job_seeker,
        sent_by_job_seeker=True,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        hiring_start_at=today - datetime.timedelta(days=200),
    )

    response = client.get(url, {"approval_ending_soon": "on"})
    assert response.context["page_obj"].object_list == [job_seeker]
    assert not hasattr(response.context["page_obj"].object_list[0], "pro_support_request_company_email")
    assertNotContains(response, "mailto:siae@example.com")


@freeze_time("2026-01-15")
def test_request_accompaniment_review_recipient_priority(client):
    organization = PrescriberOrganizationWith2MembershipFactory(authorized=True)
    user = organization.members.first()
    client.force_login(user)
    url = reverse("job_seekers_views:list")
    today = datetime.date(2026, 1, 15)

    job_seeker = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        author=user,
        author_prescriber_organization=organization,
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(
        user=job_seeker,
        start_at=today - datetime.timedelta(days=600),
        end_at=today + datetime.timedelta(days=30),
    )
    # Fallback source: the last accepted job application SIAE.
    JobApplicationFactory(
        job_seeker=job_seeker,
        sent_by_job_seeker=True,
        to_company__email="candidature@example.com",
        state=JobApplicationState.ACCEPTED,
        hiring_start_at=today - datetime.timedelta(days=200),
    )
    # Priority source: the ASP contract SIAE ending the latest wins over an older contract and the
    # accepted job application.
    ContractFactory(
        job_seeker=job_seeker,
        company__email="vieux-contrat@example.com",
        start_date=today - datetime.timedelta(days=800),
        end_date=today - datetime.timedelta(days=400),
    )
    ContractFactory(
        job_seeker=job_seeker,
        company__email="contrat-asp@example.com",
        start_date=today - datetime.timedelta(days=200),
        end_date=today + datetime.timedelta(days=20),
    )

    response = client.get(url, {"approval_ending_soon": "on"})
    assertContains(response, "mailto:contrat-asp@example.com")
    assertNotContains(response, "mailto:candidature@example.com")
