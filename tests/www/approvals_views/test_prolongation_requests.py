import factory
import httpx
import pytest
from django.contrib import messages
from django.core.files.storage import default_storage
from django.template import loader
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertMessages, assertNumQueries, assertRedirects

from itou.approvals.enums import (
    ProlongationReason,
    ProlongationRequestDenyProposedAction,
    ProlongationRequestDenyReason,
    ProlongationRequestStatus,
)
from itou.files.models import File
from tests.approvals import factories as approvals_factories
from tests.prescribers import factories as prescribers_factories
from tests.users import factories as users_factories
from tests.utils.test import BASE_NUM_QUERIES, parse_response_to_soup


@pytest.mark.parametrize(
    "authorized_organization,expected",
    [
        (False, 404),
        (True, 200),
    ],
)
def test_list_view_access(client, authorized_organization, expected):
    client.force_login(users_factories.PrescriberFactory(membership__organization__authorized=authorized_organization))

    response = client.get(reverse("approvals:prolongation_requests_list"))
    assert response.status_code == expected


def test_empty_list_view(snapshot, client):
    prescriber = prescribers_factories.PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
    client.force_login(prescriber)

    num_queries = (
        BASE_NUM_QUERIES
        + 1  # fetch django session
        + 1  # fetch user
        + 1  # check user memberships
        + 1  # count prolongation requests rows (from pager)
        + 1  # `is_prescriber_with_authorized_org()` in nav
        + 3  # savepoint, update session, release savepoint
    )
    with assertNumQueries(num_queries):
        response = client.get(reverse("approvals:prolongation_requests_list"))
    assert str(parse_response_to_soup(response, ".s-section .c-box")) == snapshot


def test_list_view(snapshot, client):
    prolongation_request = approvals_factories.ProlongationRequestFactory(for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    num_queries = (
        BASE_NUM_QUERIES
        + 1  # fetch django session
        + 1  # fetch user
        + 1  # check user memberships
        + 1  # fetch prolongation requests rows
        + 1  # count prolongation requests rows (from pager)
        + 1  # `is_prescriber_with_authorized_org()` in nav
        + 3  # savepoint, update session, release savepoint
    )
    with assertNumQueries(num_queries):
        response = client.get(reverse("approvals:prolongation_requests_list"))
    assert str(parse_response_to_soup(response, ".s-section .c-box")) == snapshot


def test_list_view_only_pending_filter(client):
    pending_prolongation_request = approvals_factories.ProlongationRequestFactory(
        status=ProlongationRequestStatus.PENDING,
    )
    other_prolongation_requests = approvals_factories.ProlongationRequestFactory.create_batch(
        2,
        status=factory.Iterator([ProlongationRequestStatus.GRANTED, ProlongationRequestStatus.DENIED]),
        prescriber_organization=pending_prolongation_request.prescriber_organization,
    )
    client.force_login(pending_prolongation_request.validated_by)

    response = client.get(reverse("approvals:prolongation_requests_list"))
    assert set(response.context["pager"].object_list) == {
        pending_prolongation_request,
        *other_prolongation_requests,
    }

    response = client.get(reverse("approvals:prolongation_requests_list"), data={"only_pending": True})
    assert list(response.context["pager"].object_list) == [pending_prolongation_request]


def test_show_view_access(client):
    prolongation_request, other_prolongation_request = approvals_factories.ProlongationRequestFactory.create_batch(2)

    # When we are not yet connected
    url = reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": prolongation_request.pk})
    assertRedirects(client.get(url), reverse("account_login") + f"?next={url}")

    client.force_login(prolongation_request.validated_by)
    # When the prolongation request is for the current prescriber organization
    response = client.get(
        reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": prolongation_request.pk})
    )
    assert response.status_code == 200

    # When the prolongation request is for another prescriber organization
    response = client.get(
        reverse(
            "approvals:prolongation_request_show", kwargs={"prolongation_request_id": other_prolongation_request.pk}
        )
    )
    assert response.status_code == 404

    # When the prolongation request doesn't exists
    response = client.get(reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": 0}))
    assert response.status_code == 404


def test_show_view(snapshot, client):
    prolongation_request = approvals_factories.ProlongationRequestFactory(for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    default_storage.location = "snapshot"
    response = client.get(
        reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": prolongation_request.pk})
    )
    assert str(parse_response_to_soup(response, ".s-section .col-lg-8 .c-box:last-child")) == snapshot


def test_grant_view(client):
    prolongation_request = approvals_factories.ProlongationRequestFactory(approval__user__for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    response = client.post(
        reverse("approvals:prolongation_request_grant", kwargs={"prolongation_request_id": prolongation_request.pk}),
    )
    assertRedirects(response, reverse("approvals:prolongation_requests_list"), fetch_redirect_response=False)
    assertMessages(
        response,
        [messages.Message(messages.SUCCESS, "La prolongation de John DOE a bien été acceptée.")],
    )
    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.GRANTED


def test_grant_view_is_not_accessible_by_get_method(client):
    prolongation_request = approvals_factories.ProlongationRequestFactory()
    client.force_login(prolongation_request.validated_by)

    response = client.get(
        reverse("approvals:prolongation_request_grant", kwargs={"prolongation_request_id": prolongation_request.pk})
    )
    assert response.status_code == 405


@pytest.mark.parametrize("reason", ProlongationRequestDenyReason)
def test_deny_view_for_reasons(snapshot, client, reason):
    prolongation_request = approvals_factories.ProlongationRequestFactory(for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    # Reverse all needed URL
    start_url = reverse(
        "approvals:prolongation_request_deny", kwargs={"prolongation_request_id": prolongation_request.pk}
    )
    reason_url = reverse(
        "approvals:prolongation_request_deny",
        kwargs={"prolongation_request_id": prolongation_request.pk, "step": "reason"},
    )
    reason_explanation_url = reverse(
        "approvals:prolongation_request_deny",
        kwargs={"prolongation_request_id": prolongation_request.pk, "step": "reason_explanation"},
    )
    proposed_actions_url = reverse(
        "approvals:prolongation_request_deny",
        kwargs={"prolongation_request_id": prolongation_request.pk, "step": "proposed_actions"},
    )
    end_url = reverse("approvals:prolongation_requests_list")

    # Starting the tunnel should redirect to the first step
    assertRedirects(client.get(start_url), reason_url)
    # Checking the title at least once
    assert str(parse_response_to_soup(client.get(reason_url), selector="#main .s-title-01")) == snapshot(name="title")

    # Submit data for the "reason" step
    assert str(parse_response_to_soup(client.get(reason_url), selector="#main .s-section")) == snapshot(name="reason")
    response = client.post(
        reason_url,
        {"reason-reason": reason, "prolongation_request_deny_view-current_step": "reason"},
    )
    assertRedirects(response, reason_explanation_url)

    # Submit data for the "reason_explanation" step
    assert str(parse_response_to_soup(client.get(reason_explanation_url), selector="#main .s-section")) == snapshot(
        name="reason_explanation"
    )
    response = client.post(
        reason_explanation_url,
        {
            "reason_explanation-reason_explanation": "Lorem ipsum",
            "prolongation_request_deny_view-current_step": "reason_explanation",
        },
        follow=True,
    )

    if reason is ProlongationRequestDenyReason.IAE:
        assertRedirects(response, proposed_actions_url)
        assert str(parse_response_to_soup(client.get(proposed_actions_url), selector="#main .s-section")) == snapshot(
            name="proposed_actions"
        )
        # Submit data for the "proposed_actions" step
        response = client.post(
            proposed_actions_url,
            {
                "proposed_actions-proposed_actions": list(ProlongationRequestDenyProposedAction),
                "proposed_actions-proposed_actions_explanation": "Lorem ipsum",
                "prolongation_request_deny_view-current_step": "proposed_actions",
            },
            follow=True,  # formtools will redirect to "done" step to end the tunnel, then we redirect to another URL
        )

    assertRedirects(response, end_url)
    assertMessages(response, [messages.Message(messages.SUCCESS, "La prolongation de John DOE a bien été refusée.")])
    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.DENIED
    assert prolongation_request.deny_information.reason == reason


@pytest.mark.parametrize("status", ProlongationRequestStatus)
def test_template_status_card(snapshot, status):
    prolongation_request = approvals_factories.ProlongationRequestFactory(
        for_snapshot=True,
        processed=True,
        status=status,
    )

    assert (
        loader.render_to_string(
            "approvals/prolongation_requests/_status_box.html",
            context={
                "ProlongationRequestStatus": ProlongationRequestStatus,
                "prolongation_request": prolongation_request,
            },
        )
        == snapshot
    )


class TestProlongationReportFileView:
    def test_anonymous(self, client):
        url = reverse("approvals:prolongation_request_report_file", kwargs={"prolongation_request_id": 0})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_nonexistent(self, client):
        prescriber = users_factories.PrescriberFactory(membership__organization__authorized=True)
        client.force_login(prescriber)
        response = client.get(
            reverse("approvals:prolongation_request_report_file", kwargs={"prolongation_request_id": 0})
        )
        assert response.status_code == 404

    def test_other_organization(self, client):
        prescriber = users_factories.PrescriberFactory(membership__organization__authorized=True)
        request = approvals_factories.ProlongationRequestFactory()
        client.force_login(prescriber)
        response = client.get(
            reverse(
                "approvals:prolongation_request_report_file",
                kwargs={"prolongation_request_id": request.pk},
            )
        )
        assert response.status_code == 404

    def test_no_report_file(self, client):
        org = prescribers_factories.PrescriberOrganizationFactory(authorized=True)
        prescriber = users_factories.PrescriberFactory(membership__organization=org)
        request = approvals_factories.ProlongationRequestFactory(prescriber_organization=org, report_file=None)
        client.force_login(prescriber)
        response = client.get(
            reverse(
                "approvals:prolongation_request_report_file",
                kwargs={"prolongation_request_id": request.pk},
            )
        )
        assert response.status_code == 404

    def test_ok(self, client, xlsx_file):
        org = prescribers_factories.PrescriberOrganizationFactory(authorized=True)
        prescriber = users_factories.PrescriberFactory(membership__organization=org)
        key = default_storage.save("prolongation_report/empty.xlsx", xlsx_file)
        file = File.objects.create(key=key)
        request = approvals_factories.ProlongationRequestFactory(
            prescriber_organization=org, reason=ProlongationReason.RQTH, report_file=file
        )
        client.force_login(prescriber)
        # Boto3 signed requests depend on the current date, with a second resolution.
        # See X-Amz-Date in
        # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
        with freeze_time():
            response = client.get(
                reverse(
                    "approvals:prolongation_request_report_file",
                    kwargs={"prolongation_request_id": request.pk},
                )
            )
            assertRedirects(response, default_storage.url(file.pk), fetch_redirect_response=False)
        xlsx_file.seek(0)
        assert httpx.get(response.url).content == xlsx_file.read()
