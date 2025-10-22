import random

import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual

from itou.job_applications.models import JobApplicationComment
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.job_applications.factories import JobApplicationCommentFactory, JobApplicationFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import assertSnapshotQueries, parse_response_to_soup, pretty_indented


def test_display_in_sidebar_and_tab(client, snapshot):
    company = CompanyWith2MembershipsFactory()
    job_app = JobApplicationFactory(to_company=company)
    VISIBLE_COMMENTS_COUNT = 3
    comments = JobApplicationCommentFactory.create_batch(VISIBLE_COMMENTS_COUNT, job_application=job_app)
    # A comment linked to the job app but not supposed to be seen with members of that company
    # (for various reasons such as a faulty transfer in admin)
    hidden_comment = JobApplicationCommentFactory(
        message="Un commentaire qui ne doit pas être lu.", job_application=job_app, company=CompanyFactory()
    )
    client.force_login(company.members.first())

    url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    with assertSnapshotQueries(snapshot):
        response = client.get(url)

    assertContains(
        response,
        (
            "<h3>Ajouter un commentaire"
            '<button type="button" data-bs-toggle="tooltip" data-bs-placement="top" '
            'data-bs-title="Attention à vos propos. La communication de données sensibles sur les usagers et '
            'les propos dégradants, sexistes, homophobes ou racistes ne sont pas autorisés.">'
            '<i class="ri-information-line ri-xl text-info ms-1" aria-label="Attention à vos propos. La '
            "communication de données sensibles sur les usagers et les propos dégradants, sexistes, homophobes "
            'ou racistes ne sont pas autorisés."></i>'
            "</button></h3>"
        ),
        html=True,
        count=1,
    )
    assertContains(
        response, '<label class="form-label" for="id_message">Ajouter un commentaire</label>', html=True, count=1
    )
    assertContains(response, f"<h3> Liste des commentaires ({VISIBLE_COMMENTS_COUNT})</h3>", html=True)
    for comment in comments:
        assertContains(response, comment.message, html=True)
    assertNotContains(response, hidden_comment.message, html=True)


@freeze_time("2025-09-26T12:12:12")
def test_add_comment_htmx(client, snapshot, caplog):
    location = random.choice(["sidebar", "tab"])

    company = CompanyWith2MembershipsFactory(
        membership1__user__first_name="Alice",
        membership1__user__last_name="Abolivier",
        membership2__user__first_name="Bob",
        membership2__user__last_name="Banana",
    )
    user = company.members.last()

    job_app = JobApplicationFactory(
        for_snapshot=True, to_company=company, eligibility_diagnosis=None, resume=None, answer="👋"
    )
    JobApplicationCommentFactory(
        job_application=job_app,
        created_by=company.members.first(),
        message="Cette candidate est venue 3 fois, elle est motivée.",
    )

    client.force_login(user)
    job_app_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    response = client.get(job_app_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    add_comment_url = reverse("apply:add_comment_for_company", kwargs={"job_application_id": job_app.id})
    response = client.post(
        add_comment_url,
        data={"message": "Candidate rencontrée en entretien. A recontacter dans 2 semaines.", "location": location},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(simulated_page, f"#comments-add-{location} > form", response)

    # Check that a fresh reload gets the same state
    response = client.get(job_app_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)

    comment = JobApplicationComment.objects.filter(created_by=user).order_by("-created_at").first()
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"/apply/{job_app.id}/siae/accept", "/apply/[Pk of JobApplication]/siae/accept"),
            (
                "hx-post",
                f"/apply/{job_app.id}/siae/comment/{comment.id}/delete",
                "/apply/[Pk of JobApplication]/siae/comment/[Pk of JobApplicationComment]/delete",
            ),
            (
                "data-bs-target",
                f"#delete_comment_{comment.id}_modal",
                "#delete_comment_[Pk of JobApplicationComment]_modal",
            ),
            (
                "aria-labelledby",
                f"delete_comment_{comment.id}_title",
                "delete_comment_[Pk of JobApplicationComment]_title",
            ),
            (
                "id",
                f"delete_comment_{comment.id}_modal",
                "delete_comment_[Pk of JobApplicationComment]_modal",
            ),
            (
                "id",
                f"delete_comment_{comment.id}_title",
                "delete_comment_[Pk of JobApplicationComment]_title",
            ),
        ],
    )
    assert pretty_indented(soup) == snapshot(name="add comment")
    assert f"user={user.pk} added a new comment on job_application={job_app.pk}" in caplog.messages


@pytest.mark.parametrize(
    "is_too_long, assertion, expected_comments_count", [(True, assertContains, 0), (False, assertNotContains, 1)]
)
def test_add_comment_too_long(client, is_too_long, assertion, expected_comments_count):
    location = random.choice(["sidebar", "tab"])

    company = CompanyWith2MembershipsFactory()
    user = company.members.last()
    job_app = JobApplicationFactory(to_company=company)
    comment_length = JobApplicationComment.MAX_LENGTH + int(is_too_long)

    client.force_login(user)
    add_comment_url = reverse("apply:add_comment_for_company", kwargs={"job_application_id": job_app.id})
    response = client.post(add_comment_url, data={"message": "a" * comment_length, "location": location})

    assertion(
        response,
        f"<li>Assurez-vous que cette valeur comporte au plus {JobApplicationComment.MAX_LENGTH} caractères "
        f"(actuellement {comment_length}).</li>",
        html=True,
    )
    assert JobApplicationComment.objects.count() == expected_comments_count


def test_cannot_delete_somebody_else_comment(client):
    company = CompanyWith2MembershipsFactory()
    user = company.members.last()
    client.force_login(user)
    job_app = JobApplicationFactory(to_company=company)
    other_user_comment = JobApplicationCommentFactory(job_application=job_app, created_by=company.members.first())
    comment = JobApplicationCommentFactory(job_application=job_app, created_by=user)

    delete_other_user_comment_url = reverse(
        "apply:delete_comment_for_company",
        kwargs={"job_application_id": job_app.id, "comment_id": other_user_comment.id},
    )
    response = client.post(delete_other_user_comment_url)
    assert response.status_code == 200  # returns the comments list without error
    assertQuerySetEqual(
        JobApplicationComment.objects.all(), [other_user_comment, comment], ordered=False
    )  # no comments were deleted

    delete_comment_url = reverse(
        "apply:delete_comment_for_company",
        kwargs={"job_application_id": job_app.id, "comment_id": comment.id},
    )
    response = client.post(delete_comment_url)
    assert response.status_code == 200
    assertQuerySetEqual(
        JobApplicationComment.objects.all(), [other_user_comment], ordered=False
    )  # the user's comment was deleted


def test_delete_comment_htmx(client, caplog):
    company = CompanyWith2MembershipsFactory(
        membership1__user__first_name="Alice",
        membership1__user__last_name="Abolivier",
        membership2__user__first_name="Bob",
        membership2__user__last_name="Banana",
    )
    user = company.members.last()

    job_app = JobApplicationFactory(
        for_snapshot=True, to_company=company, eligibility_diagnosis=None, resume=None, answer="👋"
    )
    other_user_comment = JobApplicationCommentFactory(
        job_application=job_app,
        created_by=company.members.first(),
        message="Cette candidate est venue 3 fois, elle est motivée.",
    )
    comment = JobApplicationCommentFactory(job_application=job_app, created_by=user, message="Rdv le 2/9.")

    client.force_login(user)
    job_app_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    response = client.get(job_app_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    delete_comment_url = reverse(
        "apply:delete_comment_for_company",
        kwargs={"job_application_id": job_app.id, "comment_id": comment.id},
    )
    delete_other_user_comment_url = reverse(
        "apply:delete_comment_for_company",
        kwargs={"job_application_id": job_app.id, "comment_id": other_user_comment.id},
    )
    assertContains(response, delete_comment_url, count=1)
    assertNotContains(response, delete_other_user_comment_url)
    response = client.post(
        delete_comment_url,
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(simulated_page, f"form[hx-post='{delete_comment_url}']", response)

    # Check that a fresh reload gets the same state
    response = client.get(job_app_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)
    assert f"user={user.pk} deleted 1 comment on job_application={job_app.pk}" in caplog.messages
