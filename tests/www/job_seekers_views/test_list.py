import datetime
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.users.models import User, UserKind
from itou.utils.templatetags.str_filters import mask_unless
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import (
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


def assert_contains_button_apply_for(response, job_seeker, with_city=True):
    city = f"&city={job_seeker.city_slug}" if with_city else ""
    assertContains(
        response,
        f"""
            <a class="btn btn-sm btn-link btn-ico-only"
                data-bs-toggle="tooltip"
                data-bs-title="Postuler pour ce candidat"
                data-matomo-event="true"
                data-matomo-category="candidature" data-matomo-action="clic"
                data-matomo-option="postuler-pour-ce-candidat"
                href="{reverse("search:employers_results")}?job_seeker={job_seeker.public_id}{city}">
                <i class="ri-draft-line" aria-label="Postuler pour ce candidat"></i>
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
        }" class="btn-link">{mask_unless(job_seeker.get_full_name(), with_personal_information)}
            </a>
        """,
        count=1,
        html=True,
    )


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_anonymous_user(client, url):
    response = client.get(url)
    assertRedirects(response, reverse("account_login") + f"?next={url}")


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_refused_access(client, url):
    for user in [
        JobSeekerFactory(),
        LaborInspectorFactory(membership=True),
        CompanyWithMembershipAndJobsFactory().members.first(),
    ]:
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 403


def test_raise_404_on_organization_tab_for_prescriber_without_org(client):
    url = reverse("job_seekers_views:list_organization")
    user = PrescriberFactory()
    client.force_login(user)
    response = client.get(url)

    assert response.status_code == 404


@pytest.mark.parametrize("with_membership, assertion", [(False, assertNotContains), (True, assertContains)])
def test_displayed_tabs(client, with_membership, assertion):
    user = PrescriberFactory(membership=with_membership)
    client.force_login(user)
    response = client.get(reverse("job_seekers_views:list"))

    assertContains(response, "Mes candidats")
    assertion(response, "Tous les candidats de la structure")


@pytest.mark.parametrize(
    "url, assertion",
    [
        (reverse("job_seekers_views:list"), assertNotContains),
        (reverse("job_seekers_views:list_organization"), assertContains),
    ],
)
def test_displayed_filters(client, url, assertion):
    user = PrescriberFactory(membership=True)
    client.force_login(user)
    response = client.get(url)

    assertion(response, "Tous les filtres")


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_empty_list(client, url, snapshot):
    client.force_login(
        PrescriberFactory(membership=True, membership__organization__not_in_territorial_experimentation=True)
    )
    response = client.get(url)
    assert str(parse_response_to_soup(response, selector="#main")) == snapshot


@freeze_time("2024-08-30")
def test_multiple(client, snapshot):
    url = reverse("job_seekers_views:list")

    # App with diagnosis but without approval
    job_app = JobApplicationFactory(
        job_seeker__first_name="Alain",
        job_seeker__last_name="Zorro",
        job_seeker__public_id="11111111-1111-1111-1111-111111111111",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        sent_by_authorized_prescriber_organisation=True,
        updated_at=timezone.now() - datetime.timedelta(days=1),
    )
    prescriber = job_app.sender
    # Other app for the same job seeker
    JobApplicationFactory(
        sender=prescriber,
        job_seeker=job_app.job_seeker,
        updated_at=timezone.now() - datetime.timedelta(days=2),
    )
    # Other app without diagnosis
    job_app2 = JobApplicationFactory(
        sender=prescriber,
        job_seeker__first_name="Bernard",
        job_seeker__last_name="Ygrec",
        job_seeker__public_id="22222222-2222-2222-2222-222222222222",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        eligibility_diagnosis=None,
    )
    # Other app with approval
    job_app3 = JobApplicationFactory(
        sender=prescriber,
        job_seeker__first_name="Charlotte",
        job_seeker__last_name="Xerus",
        job_seeker__public_id="33333333-3333-3333-3333-333333333333",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
        with_approval=True,
    )

    # Other app without address/city
    job_app4 = JobApplicationFactory(
        sender=prescriber,
        job_seeker__first_name="David",
        job_seeker__last_name="Waterford",
        job_seeker__public_id="44444444-4444-4444-4444-444444444444",
    )
    # Other app for which the current user cannot see the personal information
    unauthorized_prescriber = PrescriberFactory(membership=False)
    job_app5 = JobApplicationFactory(
        sender=unauthorized_prescriber,
        job_seeker__first_name="Edouard",
        job_seeker__last_name="Vivant",
        job_seeker__public_id="55555555-5555-5555-5555-555555555555",
        job_seeker__post_code="29200",
        job_seeker__city="Brest",
    )

    client.force_login(prescriber)
    with assertSnapshotQueries(snapshot(name="job seekers list SQL")):
        response = client.get(url)
        assert str(parse_response_to_soup(response, selector="table")) == snapshot(name="job seekers list table")

        # Address is in search URL
        for i, application in enumerate([job_app, job_app2, job_app3]):
            assert_contains_button_apply_for(response, application.job_seeker, with_city=True)

        # Job seeker does not have an address, so it is not in the URL
        assert_contains_button_apply_for(response, job_app4.job_seeker, with_city=False)

    # Current user cannot view personal information, so the city is not in the URL
    client.force_login(unauthorized_prescriber)
    response = client.get(url)
    assert_contains_button_apply_for(response, job_app5.job_seeker, with_city=False)


@freeze_time("2024-08-30")
def test_multiple_with_job_seekers_created_by_organization(client, snapshot):
    url_user = reverse("job_seekers_views:list")
    url_organization = reverse("job_seekers_views:list_organization")
    organization = PrescriberOrganizationWith2MembershipFactory(authorized=True)
    [prescriber, other_prescriber] = organization.members.all()

    # Job seeker created by this prescriber
    alain = JobSeekerFactory(
        first_name="Alain",
        last_name="Zorro",
        public_id="11111111-1111-1111-1111-111111111111",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        jobseeker_profile__created_by_prescriber_organization=organization,
    )

    # Job seeker created by another member of the organization
    bernard = JobSeekerFactory(
        first_name="Bernard",
        last_name="Ygrec",
        public_id="22222222-2222-2222-2222-222222222222",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
        jobseeker_profile__created_by_prescriber_organization=organization,
    )

    # Job seeker created by a member of the organization, but not in the organization anymore
    prescriber_not_in_org_anymore = PrescriberFactory(
        membership__organization=organization, membership__is_active=False
    )
    charlotte = JobSeekerFactory(
        first_name="Charlotte",
        last_name="Xerus",
        public_id="33333333-3333-3333-3333-333333333333",
        post_code="29200",
        city="Brest",
        created_by=prescriber_not_in_org_anymore,
        jobseeker_profile__created_by_prescriber_organization=organization,
    )

    # When applying for a job seeker already in the list, he's not shown twice
    JobApplicationFactory(
        job_seeker=alain,
        sender=prescriber,
        sent_by_authorized_prescriber_organisation=True,
        updated_at=timezone.now() - datetime.timedelta(days=1),
    )

    # Job seeker created by the prescriber but for another organization; will be shown
    other_organization = PrescriberOrganizationFactory()
    david = JobSeekerFactory(
        first_name="David",
        last_name="Waterford",
        public_id="44444444-4444-4444-4444-444444444444",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        jobseeker_profile__created_by_prescriber_organization=other_organization,
    )

    # Job seeker created by someone else, for another organization
    edouard = JobSeekerFactory(
        first_name="Edouard",
        last_name="Vivant",
        public_id="55555555-5555-5555-5555-555555555555",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
        jobseeker_profile__created_by_prescriber_organization=other_organization,
    )

    client.force_login(prescriber)
    with assertSnapshotQueries(snapshot(name="job seekers created by organization list with SQL")):
        response = client.get(url_organization)
        soup = parse_response_to_soup(response, selector="tbody")
        assert str(soup) == snapshot(name="job seekers list tbody")

        # Job seekers are displayed for the prescriber
        for job_seeker in [alain, bernard, charlotte, david]:
            assert_contains_job_seeker(response, job_seeker, back_url=url_organization, with_personal_information=True)
            assert_contains_button_apply_for(response, job_seeker, with_city=True)

        # Job seeker not displayed for the prescriber
        assertNotContains(response, edouard.get_full_name())
        assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": edouard.public_id}))

    # The job seekers created by the other member of the organization are not shown in the
    # "Mes candidats" tab
    response = client.get(url_user)

    # Job seekers are displayed for the prescriber
    for job_seeker in [alain, david]:
        assert_contains_job_seeker(response, job_seeker, back_url=url_user, with_personal_information=True)
        assert_contains_button_apply_for(response, job_seeker, with_city=True)

    # Job seeker not displayed for the prescriber
    for job_seeker in [bernard, charlotte, edouard]:
        assertNotContains(response, job_seeker.get_full_name())
        assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}))


def test_job_seeker_created_for_prescription_is_shown(client):
    organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
    company = CompanyWithMembershipAndJobsFactory()
    company_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
    prescriber = organization.members.first()
    client.force_login(prescriber)
    client.get(company_url)

    # Init complete session
    session = client.session
    session_name = str(uuid.uuid4())
    session[session_name] = {
        "config": {
            "tunnel": "sender",
            "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
            "session_kind": "job-seeker-get-or-create",
        },
        "apply": {"company_pk": company.pk},
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
            "birthdate": datetime.date(2000, 1, 1),
            "lack_of_nir_reason": "TEMPORARY_NUMBER",
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
        jobseeker_profile__created_by_prescriber_organization=organization,
    )

    # Job seeker created by another member of the organization
    bernard = JobSeekerFactory(
        first_name="Bernard",
        last_name="Ygrec",
        public_id="22222222-2222-2222-2222-222222222222",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
        jobseeker_profile__created_by_prescriber_organization=organization,
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
    assert_contains_button_apply_for(response, bernard, with_city=False)


def test_job_seeker_created_by_prescriber_without_org(client):
    """
    Check that a job seeker created by an "orienteur solo" is not shared among
    all the "orienteurs solo"
    """
    prescriber = PrescriberFactory()
    other_prescriber = PrescriberFactory()
    organization = PrescriberOrganizationFactory()

    # Job seeker created by another prescriber
    alain = JobSeekerFactory(
        first_name="Alain",
        last_name="Zorro",
        public_id="11111111-1111-1111-1111-111111111111",
        post_code="29200",
        city="Brest",
        created_by=other_prescriber,
    )
    # Job seeker created by this prescriber
    bernard = JobSeekerFactory(
        first_name="Bernard",
        last_name="Ygrec",
        public_id="22222222-2222-2222-2222-222222222222",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
    )
    # Job seeker created by this prescriber when he was in an organization.
    # He is not member of it anymore, but the job seeker is still displayed.
    charlotte = JobSeekerFactory(
        first_name="Charlotte",
        last_name="Xerus",
        public_id="33333333-3333-3333-3333-333333333333",
        post_code="29200",
        city="Brest",
        created_by=prescriber,
        jobseeker_profile__created_by_prescriber_organization=organization,
    )

    client.force_login(prescriber)
    response = client.get(reverse("job_seekers_views:list"))
    assertNotContains(response, alain.get_full_name())
    assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": alain.public_id}))

    assert_contains_job_seeker(response, bernard, with_personal_information=True)
    assert_contains_button_apply_for(response, bernard, with_city=True)

    assert_contains_job_seeker(response, charlotte, with_personal_information=True)
    assert_contains_button_apply_for(response, charlotte, with_city=True)


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_htmx_job_seeker_filter(client, url):
    job_app = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
    prescriber = job_app.sender
    other_app = JobApplicationFactory(sender=prescriber)
    client.force_login(prescriber)
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
    prescriber = PrescriberFactory()
    a_b_job_seeker = JobApplicationFactory(
        sender=prescriber, job_seeker__first_name="A_something", job_seeker__last_name="B_something"
    ).job_seeker
    created_job_seeker = JobApplicationFactory(
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="Zorro",
        job_seeker__last_name="Martin",
    ).job_seeker
    c_d_job_seeker = JobApplicationFactory(
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__last_login=timezone.now(),
        job_seeker__first_name="C_something",
        job_seeker__last_name="D_something",
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
        (a_b_job_seeker.pk, "A… B…"),
        (c_d_job_seeker.pk, "C… D…"),
        (created_job_seeker.pk, "Zorro MARTIN"),
    ]


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_filtered_by_eligibility_state(client, url):
    """
    Éligibilité "IAE valide": show job seekers with valid diagnosis OR with valid approval.
    Éligibilité "IAE à valider": show job seekers without valid diagnosis AND without valid approval.
    """
    prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
    client.force_login(prescriber)
    # Eligibility validated
    job_seeker_valid_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="valid eligibility, no approval",
    ).job_seeker
    job_seeker_valid_geiq_eligibility_no_approval = GEIQEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="valid geiq eligibility, no approval",
    ).job_seeker
    job_seeker_expired_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        expired=True,
        job_seeker__first_name="expired eligibility, valid approval",
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_valid_approval)
    job_seeker_valid_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="valid eligibility, valid approval",
    ).job_seeker
    ApprovalFactory(user=job_seeker_valid_eligibility_valid_approval)

    # Eligibility to validate
    job_seeker_expired_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        expired=True,
        job_seeker__first_name="expired eligibility, no approval",
    ).job_seeker

    response = client.get(url, {"eligibility_validated": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_expired_eligibility_valid_approval,
        job_seeker_valid_eligibility_no_approval,
        job_seeker_valid_eligibility_valid_approval,
    ]

    response = client.get(url, {"eligibility_pending": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_expired_eligibility_no_approval,
        job_seeker_valid_geiq_eligibility_no_approval,
    ]

    response = client.get(url, {"eligibility_validated": "on", "eligibility_pending": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_expired_eligibility_no_approval,
        job_seeker_expired_eligibility_valid_approval,
        job_seeker_valid_eligibility_no_approval,
        job_seeker_valid_eligibility_valid_approval,
        job_seeker_valid_geiq_eligibility_no_approval,
    ]


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_filtered_by_approval_state(client, url):
    prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
    client.force_login(prescriber)

    job_seeker_expired_eligibility_valid_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        expired=True,
        job_seeker__first_name="expired eligibility, valid approval",
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_valid_approval)

    job_seeker_expired_eligibility_expired_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        expired=True,
        job_seeker__first_name="expired eligibility, expired approval",
    ).job_seeker
    ApprovalFactory(user=job_seeker_expired_eligibility_expired_approval, expired=True)

    job_seeker_valid_eligibility_no_approval = IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="valid eligibility, no approval",
    ).job_seeker

    response = client.get(url, {"pass_iae_active": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_expired_eligibility_valid_approval]

    response = client.get(url, {"pass_iae_expired": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_expired_eligibility_expired_approval]

    response = client.get(url, {"no_pass_iae": "on"})
    assert response.context["page_obj"].object_list == [job_seeker_valid_eligibility_no_approval]

    response = client.get(url, {"pass_iae_expired": "on", "no_pass_iae": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_expired_eligibility_expired_approval,
        job_seeker_valid_eligibility_no_approval,
    ]

    response = client.get(url, {"pass_iae_active": "on", "pass_iae_expired": "on", "no_pass_iae": "on"})
    assert response.context["page_obj"].object_list == [
        job_seeker_expired_eligibility_expired_approval,
        job_seeker_expired_eligibility_valid_approval,
        job_seeker_valid_eligibility_no_approval,
    ]


def test_filtered_by_organization_members(client):
    organization = PrescriberOrganizationWith2MembershipFactory(authorized=True)
    prescriber = organization.members.first()
    member = organization.members.last()
    old_member = PrescriberMembershipFactory(organization=organization, user__is_active=False).user
    other_prescriber_not_in_orga = PrescriberFactory()

    job_seeker_created_by_user = JobSeekerFactory(
        created_by=prescriber,
        jobseeker_profile__created_by_prescriber_organization=organization,
        first_name="created_by_user",
        last_name="Zorro",
    )
    job_seeker_created_by_member = JobSeekerFactory(
        created_by=member,
        jobseeker_profile__created_by_prescriber_organization=organization,
        first_name="created_by_member",
        last_name="Zorro",
    )
    job_seeker_created_by_old_member = JobSeekerFactory(
        created_by=old_member,
        jobseeker_profile__created_by_prescriber_organization=organization,
        first_name="created_by_old_member",
        last_name="Zorro",
    )

    job_seeker_applied_by_user = JobApplicationFactory(
        sender=prescriber,
        sender_prescriber_organization=organization,
        job_seeker__first_name="applied_by_user",
        job_seeker__last_name="Zorro",
    ).job_seeker
    job_seeker_applied_by_member = JobApplicationFactory(
        sender=member,
        sender_prescriber_organization=organization,
        job_seeker__first_name="applied_by_member",
        job_seeker__last_name="Zorro",
        updated_at=timezone.now() - datetime.timedelta(days=1),
    ).job_seeker
    job_seeker_applied_by_old_member = JobApplicationFactory(
        sender=old_member,
        sender_prescriber_organization=organization,
        job_seeker__first_name="applied_by_old_member",
        job_seeker__last_name="Zorro",
    ).job_seeker
    job_seeker_applied_by_user_created_by_user_not_in_orga = JobApplicationFactory(
        sender=prescriber,
        job_seeker__first_name="applied_by_user_created_by_other_user_not_in_orga",
        job_seeker__last_name="Zorro",
        job_seeker__created_by=other_prescriber_not_in_orga,
    ).job_seeker

    client.force_login(prescriber)
    url = reverse("job_seekers_views:list_organization")

    response = client.get(url)
    assert response.context["page_obj"].object_list == [
        job_seeker_applied_by_member,
        job_seeker_applied_by_old_member,
        job_seeker_applied_by_user_created_by_user_not_in_orga,
        job_seeker_applied_by_user,
        job_seeker_created_by_member,
        job_seeker_created_by_old_member,
        job_seeker_created_by_user,
    ]

    for organization_member in [prescriber, member, old_member]:
        assertContains(response, organization_member.get_full_name())
    assertNotContains(response, other_prescriber_not_in_orga.get_full_name())

    response = client.get(url, {"organization_members": member.pk})
    assert response.context["page_obj"].object_list == [job_seeker_applied_by_member, job_seeker_created_by_member]

    response = client.get(url, {"organization_members": old_member.pk})
    assert response.context["page_obj"].object_list == [
        job_seeker_applied_by_old_member,
        job_seeker_created_by_old_member,
    ]


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_htmx_filters(client, url):
    prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
    client.force_login(prescriber)

    IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker__created_by=prescriber,
    )
    response = client.get(url)
    page = parse_response_to_soup(response, selector="#main")
    # Simulate the data-sync-with and check both checkboxes.
    eligibility_validated_checkboxes = page.find_all("input", attrs={"name": "eligibility_validated"})
    assert len(eligibility_validated_checkboxes) == 2
    for checkbox in eligibility_validated_checkboxes:
        checkbox["checked"] = ""

    response = client.get(url, {"eligibility_validated": "on"}, headers={"HX-Request": "true"})
    update_page_with_htmx(page, f"form[hx-get='{url}']", response)

    response = client.get(url, {"eligibility_validated": "on"})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_job_seekers_order(client, url, subtests):
    prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
    c_d_job_seeker = JobApplicationFactory(
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="Charles",
        job_seeker__last_name="Deux candidatures",
    ).job_seeker
    JobApplicationFactory(sender=prescriber, job_seeker=c_d_job_seeker)
    created_job_seeker = JobSeekerFactory(
        created_by=prescriber,
        first_name="Zorro",
        last_name="Martin",
    )
    second_created_job_seeker = JobSeekerFactory(
        created_by=prescriber,
        first_name="Zorro",
        last_name="Martin",
    )
    a_b_job_seeker = JobApplicationFactory(
        sender=prescriber, job_seeker__first_name="Alice", job_seeker__last_name="Berger"
    ).job_seeker

    client.force_login(prescriber)

    expected_order = {
        "full_name": [a_b_job_seeker, c_d_job_seeker, created_job_seeker, second_created_job_seeker],
        "job_applications_nb": [created_job_seeker, second_created_job_seeker, a_b_job_seeker, c_d_job_seeker],
        "last_updated_at": [c_d_job_seeker, a_b_job_seeker, created_job_seeker, second_created_job_seeker],
    }

    with subtests.test(order="<missing_value>"):
        response = client.get(url)
        assert response.context["page_obj"].object_list == expected_order["full_name"]

    with subtests.test(order="<invalid_value>"):
        response = client.get(url, {"order": "invalid_value"})
        assert response.context["page_obj"].object_list == expected_order["full_name"]

    for order, job_seekers in expected_order.items():
        with subtests.test(order=order):
            response = client.get(url, {"order": order})
            assert response.context["page_obj"].object_list == job_seekers

            response = client.get(url, {"order": f"-{order}"})
            assert response.context["page_obj"].object_list == list(reversed(job_seekers))


@pytest.mark.parametrize("url", [reverse("job_seekers_views:list"), reverse("job_seekers_views:list_organization")])
def test_htmx_order(client, url):
    job_app = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
    prescriber = job_app.sender
    other_app = JobApplicationFactory(sender=prescriber)
    client.force_login(prescriber)
    response = client.get(url)

    assertContains(response, "2 résultats")
    assertContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id}))
    assertContains(
        response, reverse("job_seekers_views:details", kwargs={"public_id": other_app.job_seeker.public_id})
    )
    simulated_page = parse_response_to_soup(response)

    ORDER_ID = "id_order"
    LAST_UPDATED_AT_ASC = "last_updated_at"

    [sort_by_last_updated_at_button] = simulated_page.find_all(
        "button", {"data-emplois-setter-value": LAST_UPDATED_AT_ASC}
    )
    assert sort_by_last_updated_at_button["data-emplois-setter-target"] == f"#{ORDER_ID}"
    [order_input] = simulated_page.find_all(id=ORDER_ID)
    # Simulate click on button
    order_input["value"] = LAST_UPDATED_AT_ASC
    response = client.get(url, {"order": LAST_UPDATED_AT_ASC}, headers={"HX-Request": "true"})
    update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
    response = client.get(url, {"order": LAST_UPDATED_AT_ASC})
    assertContains(response, "2 résultats")
    assertContains(response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id}))
    assertContains(
        response, reverse("job_seekers_views:details", kwargs={"public_id": other_app.job_seeker.public_id})
    )
    fresh_page = parse_response_to_soup(response)
    assertSoupEqual(simulated_page, fresh_page)
