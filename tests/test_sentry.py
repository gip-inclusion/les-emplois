import json
import re

import httpx
import pytest
import sentry_sdk
from django.conf import settings

from config.sentry import HTTP_QUERY_SENSITIVE_KEYS
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import certify_criterion_with_api_particulier
from itou.utils.apis import api_particulier
from itou.utils.logging import REDACTED
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory


pytestmark = pytest.mark.usefixtures("clean_sentry_scope")


@pytest.fixture(name="clean_sentry_scope")
def clean_sentry_scope_fixture():
    """Isolate the test from the breadcrumbs left behind by the previous ones.

    The SDK keeps its scopes for the whole process, and an event is built from the
    breadcrumbs of the isolation scope *and* of the current one. Without forking
    both, every HTTP request and INFO log of the test suite ends up in the events
    captured here. Forking means the buffers can be emptied without affecting the
    rest of the run.
    """
    with sentry_sdk.isolation_scope() as isolation_scope, sentry_sdk.new_scope() as scope:
        for forked_scope in (isolation_scope, scope):
            forked_scope.clear()  # clear the entire scope, including breadcrumbs, tags, extras, etc.
        yield


def test_before_send_http_breadcrumb_sanitizer(mocker, respx_mock):
    mocker.spy(sentry_sdk.client._Client, "_prepare_event")
    url = "https://example.com/"
    params = {
        "foobar": 34,
        "nomNaissance": "Martin",
        "prenoms[]": "Jean",
        "jourDateNaissance": 12,
        "moisDateNaissance": 5,
        "anneeDateNaissance": 1980,
    }
    respx_mock.get(url, params=params).mock(return_value=httpx.Response(418))
    httpx.get(url, params=params)
    sentry_sdk.capture_message("Test message")
    assert sentry_sdk.client._Client._prepare_event.call_count == 1
    assert sentry_sdk.client._Client._prepare_event.spy_return["message"] == "Test message"
    http_breadcrumbs = [
        breadcrumb
        for breadcrumb in sentry_sdk.client._Client._prepare_event.spy_return["breadcrumbs"]["values"]
        if breadcrumb["type"] == "http"
    ]
    [http_breadcrumb] = http_breadcrumbs
    assert http_breadcrumb["data"]["http.query"] == (
        "foobar=34&nomNaissance=_REDACTED_&prenoms%5B%5D=_REDACTED_&jourDateNaissance=_REDACTED_&moisDateNaissance=_REDACTED_&anneeDateNaissance=_REDACTED_"
    )


@pytest.mark.usefixtures("api_particulier_settings")
def test_no_pii_in_event_when_api_particulier_is_down(mocker, respx_mock):
    """The identity of the job seeker must not reach Sentry when API Particulier fails."""
    diagnosis = IAEEligibilityDiagnosisFactory(
        certifiable=True,
        criteria_kinds=[AdministrativeCriteriaKind.RSA],
        job_seeker__first_name="Jean-Michel",
        job_seeker__last_name="Tardiveau",
        # born in France also sends the birth place to the API
        job_seeker__born_outside_france=False,
        job_seeker__born_in_france=True,
    )
    criterion = diagnosis.selected_administrative_criteria.get()
    endpoint = api_particulier.ENDPOINTS[AdministrativeCriteriaKind.RSA]
    respx_mock.get(settings.API_PARTICULIER_BASE_URL + endpoint).respond(502, text="Bad Gateway (non-JSON response)")
    mocker.spy(sentry_sdk.client._Client, "_prepare_event")

    # This is what the Huey integration does with a failing task
    try:
        certify_criterion_with_api_particulier(criterion)
    except httpx.HTTPStatusError:
        sentry_sdk.capture_exception()
    else:
        pytest.fail("API Particulier errors should bubble up so that the task is retried.")

    assert sentry_sdk.client._Client._prepare_event.call_count == 1
    event = sentry_sdk.client._Client._prepare_event.spy_return
    payload = json.dumps(event, default=repr)
    assert '"vars"' in payload  # guard against a false negative
    payload = payload.upper()
    for pii in [diagnosis.job_seeker.first_name, diagnosis.job_seeker.last_name]:
        assert pii.upper() not in payload
    # The birth date and birth place are digits, which collide with unrelated numbers of the
    # event (package versions, event ids, …), so they cannot be looked up as-is
    sensitive_keys = "|".join(re.escape(key.removesuffix("[]")) for key in HTTP_QUERY_SENSITIVE_KEYS)
    for match in re.finditer(rf"(?:{sensitive_keys})(.{{0,32}})", payload):
        # What separates a key from its value depends on where it appears: "=" in a query
        # string, "': '" in the repr of the params dict, escaped quotes in nested JSON…
        value = match.group(1).lstrip("\\'\": =")
        assert value.startswith(REDACTED), f"PII in the Sentry event: {match.group(0)}"
