import logging

import httpx
import pytest
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.companies.factories import CompanyMembershipFactory
from tests.users.factories import ItouStaffFactory


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


def test_query_values_of_an_outgoing_url_are_redacted(console_log):
    """Every logger reaching the console handler is covered, not just the two hosts of old."""
    url = httpx.URL("https://particulier.api.gouv.fr/v3/dss/identite?nomNaissance=TARDIVEAU&page=2")
    logging.getLogger("itou.utils.apis.some_client").info('HTTP Request: GET %s "HTTP/1.1 502"', url)

    logged = console_log.getvalue()
    assert "TARDIVEAU" not in logged
    assert "nomNaissance=_REDACTED_" in logged
    assert "page=2" in logged  # which page was asked for names nobody


def test_url_carried_by_an_exception_message_is_redacted(console_log):
    """httpx builds the message of its errors from the URL, query string included."""
    url = "https://particulier.api.gouv.fr/v3/dss/identite?nomNaissance=TARDIVEAU"
    request = httpx.Request("GET", url)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        httpx.Response(502, request=request).raise_for_status()

    logging.getLogger("itou.utils.apis.some_client").info("Error while requesting: %s", exc_info.value)

    logged = console_log.getvalue()
    assert "TARDIVEAU" not in logged
    assert "nomNaissance=_REDACTED_" in logged


def test_url_in_a_traceback_is_redacted(console_log):
    """`logger.exception` also writes the message of the exception and its traceback."""
    request = httpx.Request("GET", "https://particulier.api.gouv.fr/v3/dss/identite?nomNaissance=TARDIVEAU")
    try:
        httpx.Response(502, request=request).raise_for_status()
    except httpx.HTTPStatusError:
        logging.getLogger("itou.utils.apis.some_client").exception("Unable to fetch and parse user data")

    logged = console_log.getvalue()
    assert '"error.stack"' in logged  # guard against a false negative
    assert "TARDIVEAU" not in logged
    assert "nomNaissance=_REDACTED_" in logged


def test_url_in_an_exception_logged_as_the_message_is_redacted(console_log):
    request = httpx.Request("GET", "https://particulier.api.gouv.fr/v3/dss/identite?nomNaissance=TARDIVEAU")
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        httpx.Response(502, request=request).raise_for_status()

    logging.getLogger("itou.utils.apis.some_client").error(exc_info.value)

    logged = console_log.getvalue()
    assert "TARDIVEAU" not in logged
    assert "nomNaissance=_REDACTED_" in logged


def test_email_addressing_a_contact_is_redacted(console_log):
    """Brevo names a contact by its email address in the path, where no query rule reaches it."""
    url = httpx.URL("https://api.brevo.com/v3/contacts/jean-michel@example.com?identifierType=email_id")
    logging.getLogger("itou.utils.apis.some_client").info('HTTP Request: DELETE %s "HTTP/1.1 404"', url)

    logged = console_log.getvalue()
    assert "jean-michel@example.com" not in logged
    assert "/contacts/_REDACTED_" in logged


def test_email_in_a_message_is_redacted(console_log):
    logging.getLogger("itou.archive.tasks").warning(
        "Attempting to delete email %s, remaining %d retries", "jean-michel@example.com", 0
    )

    logged = console_log.getvalue()
    assert "jean-michel@example.com" not in logged
    assert '"message": "Attempting to delete email _REDACTED_, remaining 0 retries"' in logged


def test_the_record_is_left_alone(console_log, caplog):
    """Only the output of the console handler is redacted: the other handlers, Sentry's among them, see the record."""
    url = httpx.URL("https://particulier.api.gouv.fr/v3/dss/identite?nomNaissance=TARDIVEAU")
    logging.getLogger("itou.utils.apis.some_client").info("Request failed for %s", url)

    assert "nomNaissance=_REDACTED_" in console_log.getvalue()
    [record] = caplog.records
    assert record.msg == "Request failed for %s"
    assert record.args == (url,)


def test_a_record_without_a_url_is_left_alone(console_log):
    logging.getLogger("itou.utils.apis.some_client").info("Sent %d emails to %s", 3, "the queue")

    assert '"message": "Sent 3 emails to the queue"' in console_log.getvalue()


def test_the_transition_handler_does_not_redact(capture_stream_handler_log):
    """The geocoding logger quotes a home address in the URL it logs, and is reviewed before moving over.

    Asserting it rather than assuming it: this is a deliberate hole, and it should close loudly.
    """
    logger = logging.getLogger("itou.utils.apis.geocoding")
    with capture_stream_handler_log(logger) as captured:
        logger.info("Error while requesting `%s`", "https://ban/search/?q=112+rue+de+la+Croix-Nivert")

    assert "Croix-Nivert" in captured.getvalue()
