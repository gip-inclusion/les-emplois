import httpx
import sentry_sdk


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
