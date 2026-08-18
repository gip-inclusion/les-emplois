import httpx
import sentry_sdk


def test_before_send_http_breadcrumb_sanitizer(mocker, respx_mock):
    mocker.spy(sentry_sdk.client._Client, "_prepare_event")
    with sentry_sdk.new_scope() as scope:
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
        scope.capture_message("Test message")
    assert sentry_sdk.client._Client._prepare_event.call_count == 1
    assert sentry_sdk.client._Client._prepare_event.spy_return["message"] == "Test message"
    http_breacrumbs = [
        breadcrumb
        for breadcrumb in sentry_sdk.client._Client._prepare_event.spy_return["breadcrumbs"]["values"]
        if breadcrumb["type"] == "http"
    ]
    [http_breadcrumb] = http_breacrumbs
    assert http_breadcrumb["data"]["http.query"] == (
        "foobar=34&nomNaissance=_REDACTED_&prenoms%5B%5D=_REDACTED_&jourDateNaissance=_REDACTED_&moisDateNaissance=_REDACTED_&anneeDateNaissance=_REDACTED_"
    )
