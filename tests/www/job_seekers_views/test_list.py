import datetime

from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.utils.templatetags.str_filters import mask_unless
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
)
from tests.users.factories import JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


def assert_contains_button_apply_for(response, job_seeker, with_city=True, with_intro_js=False):
    id_intro_js = 'id="introJsBtnPostuler"' if with_intro_js else ""
    city = f"&city={job_seeker.city_slug}" if with_city else ""
    assertContains(
        response,
        f"""
            <a class="btn btn-sm btn-link btn-ico-only"
                aria-label="Postuler pour ce candidat"
                data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"
                data-matomo-option="postuler-pour-ce-candidat"
                {id_intro_js}
                href="{reverse("search:employers_results")}?job_seeker={job_seeker.public_id}{city}">
                <i class="ri-draft-line" aria-hidden="true" data-bs-toggle="tooltip"
                data-bs-title="Postuler pour ce candidat">
                </i>
            </a>
        """,
        count=1,
        html=True,
    )


def assert_contains_job_seeker(response, job_seeker, with_personal_information=True):
    assertContains(
        response,
        f"""
            <a href="{reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})}?back_url={
            reverse("job_seekers_views:list")
        }" class="btn-link">{mask_unless(job_seeker.get_full_name(), with_personal_information)}
            </a>
        """,
        count=1,
        html=True,
    )


def test_anonymous_user(client):
    url = reverse("job_seekers_views:list")
    response = client.get(url)
    assertRedirects(response, reverse("account_login") + f"?next={url}")


def test_refused_access(client):
    url = reverse("job_seekers_views:list")

    for user in [
        JobSeekerFactory(),
        LaborInspectorFactory(membership=True),
        CompanyWithMembershipAndJobsFactory().members.first(),
    ]:
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 403


def test_empty_list(client, snapshot):
    url = reverse("job_seekers_views:list")

    client.force_login(PrescriberFactory())
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
        assert str(parse_response_to_soup(response, selector="tbody")) == snapshot(name="job seekers list tbody")

        # Address is in search URL
        for i, application in enumerate([job_app, job_app2, job_app3]):
            assert_contains_button_apply_for(response, application.job_seeker, with_city=True, with_intro_js=i == 0)

        # Job seeker does not have an address, so it is not in the URL
        assert_contains_button_apply_for(response, job_app4.job_seeker, with_city=False)

    # Current user cannot view personal information, so the city is not in the URL
    client.force_login(unauthorized_prescriber)
    response = client.get(url)
    parse_response_to_soup(response, selector="tbody")
    assert_contains_button_apply_for(response, job_app5.job_seeker, with_city=False, with_intro_js=True)


@freeze_time("2024-08-30")
def test_multiple_with_job_seekers_created_by_organization(client, snapshot):
    url = reverse("job_seekers_views:list")
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
        response = client.get(url)
        soup = parse_response_to_soup(response, selector="tbody")
        assert str(soup) == snapshot(name="job seekers list tbody")

        # Job seekers are displayed for the prescriber
        for job_seeker in [alain, bernard, charlotte, david]:
            assert_contains_job_seeker(response, job_seeker, with_personal_information=True)
            assert_contains_button_apply_for(response, job_seeker, with_city=True, with_intro_js=job_seeker == alain)

        # Job seeker not displayed for the prescriber
        assertNotContains(response, edouard.get_full_name())
        assertNotContains(response, reverse("job_seekers_views:details", kwargs={"public_id": edouard.public_id}))


@freeze_time("2024-08-30")
def test_multiple_with_job_seekers_created_by_unauthorized_organization(client):
    url = reverse("job_seekers_views:list")
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

    response = client.get(url)
    # A job seeker created by the user is shown with personal information
    assert_contains_job_seeker(response, alain, with_personal_information=True)
    assert_contains_button_apply_for(response, alain, with_city=True, with_intro_js=True)

    # A job seeker created by a member of the unauthorized organization is shown *without* personal information
    assert_contains_job_seeker(response, bernard, with_personal_information=False)
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
    assert_contains_button_apply_for(response, bernard, with_city=True, with_intro_js=True)

    assert_contains_job_seeker(response, charlotte, with_personal_information=True)
    assert_contains_button_apply_for(response, charlotte, with_city=True)


def test_htmx_job_seeker_filter(client):
    url = reverse("job_seekers_views:list")

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
