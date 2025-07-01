import io
import json
import logging
import uuid
from unittest.mock import patch

from django.core import management
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.companies.factories import CompanyMembershipFactory
from tests.users.factories import (
    ItouStaffFactory,
)


def test_log_current_organization(client):
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)
    root_logger = logging.getLogger()
    stream_handler = root_logger.handlers[0]
    captured = io.StringIO()
    assert isinstance(stream_handler, logging.StreamHandler)
    # caplog cannot be used since the organization_id is written by the log formatter
    # capsys/capfd did not want to work because https://github.com/pytest-dev/pytest/issues/5997
    with patch.object(stream_handler, "stream", captured):
        response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    # Check that the organization_id is properly logged to stdout
    assert f'"usr.organization_id": {membership.company_id}' in captured.getvalue()


def test_log_current_command(client):
    root_logger = logging.getLogger()
    stream_handler = root_logger.handlers[0]
    captured = io.StringIO()
    assert isinstance(stream_handler, logging.StreamHandler)
    # caplog cannot be used since the command infos are written by the log formatter
    # capsys/capfd did not want to work because https://github.com/pytest-dev/pytest/issues/5997
    with patch.object(stream_handler, "stream", captured):
        management.call_command(
            # This could have been any other command inheriting from LoggedCommandMixin
            "delete_old_emails"
        )
    # Check that the organization_id is properly logged to stdout
    lines = captured.getvalue().splitlines()
    log = json.loads(lines[0])
    assert log["command.name"] == "itou.emails.management.commands.delete_old_emails"
    assert "command.run_uid" in log
    assert uuid.UUID(log["command.run_uid"])


def test_log_hijack_infos(client):
    LOG_KEY = "usr.hijack_history"
    dashboard_url = reverse("dashboard:index")
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)
    root_logger = logging.getLogger()
    stream_handler = root_logger.handlers[0]
    captured = io.StringIO()
    assert isinstance(stream_handler, logging.StreamHandler)
    # caplog cannot be used since the organization_id is written by the log formatter
    # capsys/capfd did not want to work because https://github.com/pytest-dev/pytest/issues/5997
    with patch.object(stream_handler, "stream", captured):
        response = client.get(dashboard_url)
    assert response.status_code == 200
    # Check that the hijack info is not there
    assert f'"usr.id": {membership.user.id}' in captured.getvalue()
    assert LOG_KEY not in captured.getvalue()

    hijacker = ItouStaffFactory(is_superuser=True)
    client.force_login(hijacker)
    response = client.post(reverse("hijack:acquire"), {"user_pk": membership.user.pk, "next": dashboard_url})
    assertRedirects(response, dashboard_url, fetch_redirect_response=False)
    captured = io.StringIO()
    # caplog cannot be used since the organization_id is written by the log formatter
    # capsys/capfd did not want to work because https://github.com/pytest-dev/pytest/issues/5997
    with patch.object(stream_handler, "stream", captured):
        response = client.get(dashboard_url)
    assert response.status_code == 200
    # Check that the hijack info is there
    assert f'"usr.id": {membership.user.id}' in captured.getvalue()
    assert f'"{LOG_KEY}": ["{hijacker.pk}"]' in captured.getvalue()
