import pytest
from django.contrib import messages
from django.template import loader
from django.urls import reverse
from pytest_django.asserts import assertNumQueries, assertRedirects

from itou.approvals.enums import ProlongationRequestStatus
from tests.approvals import factories as approvals_factories
from tests.users import factories as users_factories
from tests.utils.test import BASE_NUM_QUERIES, assertMessages, parse_response_to_soup


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


def test_list_view(snapshot, client):
    prolongation_request = approvals_factories.ProlongationRequestFactory(for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    num_queries = (
        BASE_NUM_QUERIES
        + 1  # fetch django session
        + 1  # fetch user
        + 1  # check user memberships
        + 1  # fetch organization infos
        + 1  # fetch prolongation requests rows
        + 3  # savepoint, update session, release savepoint
    )
    with assertNumQueries(num_queries):
        response = client.get(reverse("approvals:prolongation_requests_list"))
    assert str(parse_response_to_soup(response, ".s-section .c-box")) == snapshot


def test_show_view_access(client):
    prolongation_request, other_prolongation_request = approvals_factories.ProlongationRequestFactory.create_batch(2)

    # When the prolongation request is for the current prescriber organization
    client.force_login(prolongation_request.validated_by)
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

    response = client.get(
        reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": prolongation_request.pk})
    )
    assert str(parse_response_to_soup(response, ".s-section .col-lg-8 .c-box:last-child")) == snapshot


@pytest.mark.parametrize(
    "action,expected_status,expected_message",
    [
        ("grant", ProlongationRequestStatus.GRANTED, "acceptée"),
        ("deny", ProlongationRequestStatus.DENIED, "refusée"),
    ],
)
def test_show_view_action(client, action, expected_status, expected_message):
    prolongation_request = approvals_factories.ProlongationRequestFactory(approval__user__for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    response = client.post(
        reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": prolongation_request.pk}),
        {"action": action},
    )
    assertRedirects(response, reverse("approvals:prolongation_requests_list"), fetch_redirect_response=False)
    assertMessages(
        response,
        [(messages.SUCCESS, f"La prolongation de John Doe a bien été {expected_message}.")],
    )
    prolongation_request.refresh_from_db()
    assert prolongation_request.status == expected_status


def test_show_view_with_invalid_action(faker, client):
    prolongation_request = approvals_factories.ProlongationRequestFactory(approval__user__for_snapshot=True)
    client.force_login(prolongation_request.validated_by)

    response = client.post(
        reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": prolongation_request.pk}),
        {"action": faker.sentence()},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("status", ProlongationRequestStatus)
def test_template_status_card(snapshot, status):
    prolongation_request = approvals_factories.ProlongationRequestFactory(
        for_snapshot=True,
        processed=True,
        status=status,
    )

    assert (
        loader.render_to_string(
            "approvals/prolongation_requests/_status_card.html",
            context={
                "ProlongationRequestStatus": ProlongationRequestStatus,
                "prolongation_request": prolongation_request,
            },
        )
        == snapshot
    )
