import logging

from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.companies.factories import CompanyMembershipFactory
from tests.users.factories import (
    ItouStaffFactory,
)


def test_log_current_organization(capture_stream_handler_log, client):
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)
    with capture_stream_handler_log(logging.getLogger()) as captured:
        response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    # Check that the organization_id is properly logged to stdout
    assert f'"usr.organization_id": {membership.company_id}' in captured.getvalue()


def test_log_hijack_infos(capture_stream_handler_log, client):
    LOG_KEY = "usr.hijack_history"
    dashboard_url = reverse("dashboard:index")
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)
    with capture_stream_handler_log(logging.getLogger()) as captured:
        response = client.get(dashboard_url)
    assert response.status_code == 200
    # Check that the hijack info is not there
    assert f'"usr.id": {membership.user.id}' in captured.getvalue()
    assert LOG_KEY not in captured.getvalue()

    hijacker = ItouStaffFactory(is_superuser=True)
    client.force_login(hijacker)
    response = client.post(reverse("hijack:acquire"), {"user_pk": membership.user.pk, "next": dashboard_url})
    assertRedirects(response, dashboard_url, fetch_redirect_response=False)
    with capture_stream_handler_log(logging.getLogger()) as captured:
        response = client.get(dashboard_url)
    assert response.status_code == 200
    # Check that the hijack info is there
    assert f'"usr.id": {membership.user.id}' in captured.getvalue()
    assert f'"{LOG_KEY}": ["{hijacker.pk}"]' in captured.getvalue()
