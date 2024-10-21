import datetime

from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertRedirects

from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


def test_anonymous_user(client):
    url = reverse("job_seekers_views:list")
    response = client.get(url)
    assertRedirects(response, reverse("account_login") + f"?next={url}")


def test_refused_access(client):
    url = reverse("job_seekers_views:list")

    for user in [JobSeekerFactory(), LaborInspectorFactory(membership=True)]:
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
        job_seeker_with_address=False,
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
        for application in (job_app, job_app2, job_app3):
            assertContains(
                response,
                f"""
                <a class="btn btn-sm btn-link btn-ico-only"
                    aria-label="Postuler pour ce candidat"
                    data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"
                    data-matomo-option="postuler-pour-ce-candidat"
                    href="{reverse("search:employers_results")}?job_seeker={application.job_seeker.public_id}&city={application.job_seeker.city_slug}">
                    <i class="ri-draft-line" aria-hidden="true" data-bs-toggle="tooltip"
                    title="Postuler pour ce candidat">
                    </i>
                </a>
                """,
                html=True,
            )

        # Job seeker does not have an address, so it is not in the URL
        assertContains(
            response,
            f"""
                <a class="btn btn-sm btn-link btn-ico-only"
                    aria-label="Postuler pour ce candidat"
                    data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"
                    data-matomo-option="postuler-pour-ce-candidat"
                    href="{reverse("search:employers_results")}?job_seeker={job_app4.job_seeker.public_id}">
                    <i class="ri-draft-line" aria-hidden="true" data-bs-toggle="tooltip"
                    title="Postuler pour ce candidat">
                    </i>
                </a>
                """,
            html=True,
        )

    # Current user cannot view personal information, so the city is not in the URL
    client.force_login(unauthorized_prescriber)
    response = client.get(url)
    parse_response_to_soup(response, selector="tbody")
    assertContains(
        response,
        f"""
            <a class="btn btn-sm btn-link btn-ico-only"
                aria-label="Postuler pour ce candidat"
                data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"
                data-matomo-option="postuler-pour-ce-candidat"
                href="{reverse("search:employers_results")}?job_seeker={job_app5.job_seeker.public_id}">
                <i class="ri-draft-line" aria-hidden="true" data-bs-toggle="tooltip"
                title="Postuler pour ce candidat">
                </i>
            </a>
            """,
        html=True,
    )


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
