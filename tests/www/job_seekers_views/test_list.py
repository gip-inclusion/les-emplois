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
    JobApplicationFactory(
        sender=prescriber,
        job_seeker__first_name="Bernard",
        job_seeker__last_name="Ygrec",
        job_seeker__public_id="22222222-2222-2222-2222-222222222222",
        eligibility_diagnosis=None,
    )
    # Other app with approval
    JobApplicationFactory(
        sender=prescriber,
        job_seeker__first_name="Charlotte",
        job_seeker__last_name="Xerus",
        job_seeker__public_id="33333333-3333-3333-3333-333333333333",
        with_approval=True,
    )

    client.force_login(prescriber)
    with assertSnapshotQueries(snapshot(name="job seekers list SQL")):
        response = client.get(url)
        assert str(parse_response_to_soup(response, selector="tbody")) == snapshot(name="job seekers list tbody")


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
