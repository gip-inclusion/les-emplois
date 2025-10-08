import sentry_sdk
from sentry_sdk.consts import OP, SPANDATA


def test_before_send_http_breadcrumb_sanitizer(mocker):
    mocker.spy(sentry_sdk.client._Client, "_prepare_event")
    with sentry_sdk.new_scope() as scope:
        scope.clear()
        with sentry_sdk.start_span(op=OP.HTTP_CLIENT, name="GET /test") as span:
            span.set_data(
                SPANDATA.HTTP_QUERY,
                "foobar=34&nomNaissance=Martin&prenoms[]=Jean&jourDateNaissance=12&moisDateNaissance=5&anneeDateNaissance=1980",
            )

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
