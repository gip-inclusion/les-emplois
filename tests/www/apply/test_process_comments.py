import itertools
import random

import pytest
from django.urls import reverse
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual

from itou.job_applications.models import JobApplicationComment
from itou.www.apply.views.process_views import LAST_COMMENTS_COUNT
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, CompanyWith2MembershipsFactory
from tests.job_applications.factories import JobApplicationCommentFactory, JobApplicationFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import parse_response_to_soup, pretty_indented


def test_display_in_sidebar_and_tab(client, snapshot):
    company = CompanyWith2MembershipsFactory(subject_to_iae_rules=True)
    job_app = JobApplicationFactory(to_company=company, with_iae_eligibility_diagnosis=True)
    url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    client.force_login(company.members.first())

    # A comment linked to the job app but not supposed to be seen with members of that company
    # (for various reasons such as a faulty transfer in admin)
    hidden_comment = JobApplicationCommentFactory(
        message="Un commentaire qui ne doit pas être lu.", job_application=job_app, company=CompanyFactory()
    )

    # No visible comment yet:
    response = client.get(url)
    soup = parse_response_to_soup(response, "#comments-list-sidebar")
    assert "d-none" in soup.attrs["class"]  # sidebar comments list is hidden

    VISIBLE_COMMENTS_COUNT = 3
    comments = JobApplicationCommentFactory.create_batch(VISIBLE_COMMENTS_COUNT, job_application=job_app)

    with assertSnapshotQueries(snapshot):
        response = client.get(url)

    soup = parse_response_to_soup(response, "#comments-list-sidebar")
    assert "d-none" not in soup.attrs["class"]  # sidebar comments list is displayed
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
    assertContains(
        response,
        f'<h3 id="comments-list-tab-counter">Liste des commentaires ({VISIBLE_COMMENTS_COUNT})</h3>',
        html=True,
    )
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
        subject_to_iae_rules=True,
    )
    user = company.members.last()

    job_app = JobApplicationFactory(for_snapshot=True, to_company=company, resume=None, answer="👋")
    # Create a bunch of comments to have different comments and last_comments counts.
    other_comments = JobApplicationCommentFactory.create_batch(
        LAST_COMMENTS_COUNT + 1,
        job_application=job_app,
        created_by=company.members.first(),
        message="Cette candidate est venue 3 fois, elle est motivée.",
    )

    client.force_login(user)
    job_app_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.id})
    response = client.get(job_app_url)
    simulated_page = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            (
                "href",
                f"/gps/request-new-participant/{job_app.job_seeker.public_id}",
                "/gps/request-new-participant/[Public ID of JobSeeker]",
            ),
        ],
    )

    add_comment_url = reverse("apply:add_comment_for_company", kwargs={"job_application_id": job_app.id})
    response = client.post(
        add_comment_url,
        data={"message": "Candidate rencontrée en entretien. A recontacter dans 2 semaines.", "location": location},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(simulated_page, f"#comments-add-{location} > form", response)

    # Check that a fresh reload gets the same state
    response = client.get(job_app_url)
    assertSoupEqual(
        parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                (
                    "href",
                    f"/gps/request-new-participant/{job_app.job_seeker.public_id}",
                    "/gps/request-new-participant/[Public ID of JobSeeker]",
                ),
            ],
        ),
        simulated_page,
    )

    comment = JobApplicationComment.objects.filter(created_by=user).order_by("-created_at").first()
    soup = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=itertools.chain(
            [
                ("href", f"/apply/{job_app.id}/siae/accept", "/apply/[Pk of JobApplication]/siae/accept"),
                (
                    "href",
                    f"/gps/request-new-participant/{job_app.job_seeker.public_id}",
                    "/gps/request-new-participant/[Public ID of JobSeeker]",
                ),
                (
                    "hx-post",
                    f"/apply/{job_app.id}/siae/comment/{comment.id}/delete",
                    "/apply/[Pk of JobApplication]/siae/comment/[Pk of JobApplicationComment]/delete",
                ),
                (
                    "hx-target",
                    f"#comment-{comment.id}",
                    "#comment-[Pk of JobApplicationComment]",
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
            *(
                [
                    (
                        "id",
                        f"comment-{list_comment.id}",
                        "comment-[Pk of JobApplicationComment]",
                    )
                ]
                for list_comment in other_comments + [comment]
            ),
        ),
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


def test_cannot_delete_somebody_else_comment(client, snapshot):
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
    with assertSnapshotQueries(snapshot(name="delete comment queries")):
        response = client.post(delete_comment_url)
    assert response.status_code == 200
    assertQuerySetEqual(
        JobApplicationComment.objects.all(), [other_user_comment], ordered=False
    )  # the user's comment was deleted


def test_cannot_view_other_company_comments_on_delete(client):
    membership = CompanyMembershipFactory()
    user = membership.user

    other_membership = CompanyMembershipFactory()
    other_user = other_membership.user
    other_company = other_membership.company
    other_job_app = JobApplicationFactory(to_company=other_company)
    JobApplicationCommentFactory(job_application=other_job_app, created_by=other_user)

    client.force_login(user)

    delete_other_user_comment_url = reverse(
        "apply:delete_comment_for_company",
        kwargs={"job_application_id": other_job_app.id, "comment_id": 9999},  # any comment_id
    )
    response = client.post(delete_other_user_comment_url)
    assert response.status_code == 404


def test_delete_comment_htmx(client, caplog):
    company = CompanyWith2MembershipsFactory(
        membership1__user__first_name="Alice",
        membership1__user__last_name="Abolivier",
        membership2__user__first_name="Bob",
        membership2__user__last_name="Banana",
    )
    user = company.members.last()

    job_app = JobApplicationFactory(for_snapshot=True, to_company=company, resume=None, answer="👋")
    # Create a bunch of comments to have different comments and last_comments counts.
    other_user_comments = JobApplicationCommentFactory.create_batch(
        LAST_COMMENTS_COUNT + 2, job_application=job_app, created_by=company.members.first()
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
        kwargs={"job_application_id": job_app.id, "comment_id": other_user_comments[0].id},
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
