import random

from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains

from tests.companies.factories import CompanyWith2MembershipsFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationThreadedCommentFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import parse_response_to_soup, pretty_indented


def test_display_in_sidebar_and_tab(client):
    company = CompanyWith2MembershipsFactory()
    job_app = JobApplicationFactory(to_company=company)
    client.force_login(company.members.first())

    url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    response = client.get(url)

    assertContains(
        response,
        (
            "<h3>"
            "Ajouter un commentaire"
            '<button type="button" data-bs-toggle="tooltip" data-bs-placement="top" '
            'data-bs-title="Attention à vos propos. La communication de données sensibles sur les usagers et les '
            'propos dégradants, sexistes, homophobes ou racistes ne sont pas autorisés.">'
            '<i class="ri-information-line ri-xl text-info ms-1" aria-label="Attention à vos propos. La communication '
            "de données sensibles sur les usagers et les propos dégradants, sexistes, homophobes ou racistes ne sont "
            'pas autorisés. "></i>'
            "</button>"
            "</h3>"
        ),
        html=True,
        count=2,
    )


@freeze_time("2025-09-26T12:12:12")
def test_add_comment_htmx(client, snapshot):
    location = random.choice(["sidebar", "tab"])

    company = CompanyWith2MembershipsFactory(
        membership1__user__first_name="Alice",
        membership1__user__last_name="Abolivier",
        membership2__user__first_name="Bob",
        membership2__user__last_name="Banana",
    )

    job_app = JobApplicationFactory(
        for_snapshot=True, to_company=company, eligibility_diagnosis=None, resume=None, answer="👋"
    )
    JobApplicationThreadedCommentFactory(
        job_application=job_app,
        created_by=company.members.first(),
        message="Cette candidate est venue 3 fois, elle est motivée.",
    )

    client.force_login(company.members.last())
    job_app_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    response = client.get(job_app_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    add_comment_url = reverse("apply:add_threaded_comment_for_company", kwargs={"job_application_id": job_app.id})
    response = client.post(
        add_comment_url,
        data={"message": "Candidat rencontré en entretien. A recontacter dans 2 semaines.", "location": location},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(simulated_page, f"#comments_add_{location} > form", response)

    # Check that a fresh reload gets the same state
    response = client.get(job_app_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)

    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/apply/{job_app.id}/siae/accept", "/apply/[Pk of JobApplication]/siae/accept"),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="add comment")
