import logging

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger


def strip_sentry_sensitive_data(event, _hint):
    """
    Be very cautious about not raising any exception in this method,
    because when this happens, the initial 500 error
    never reaches the sentry servers... and it could take
    months before we realize a real error was silenced.
    Also, you cannot use the debugger here.
    """
    if "user" in event:
        # Unfortunately this does not work for the IP address
        # which keeps appearing. ¯\_(ツ)_/¯
        keys_to_delete_if_present = ["email", "username", "ip_address"]
        for key in keys_to_delete_if_present:
            if key in event["user"]:
                del event["user"][key]
        # Identify clearly users who have not logged in.
        if "id" not in event["user"]:
            event["user"]["id"] = "anonymous"
    return event


sentry_logging = LoggingIntegration(
    level=logging.INFO,  # Capture info and above as breadcrumbs.
    event_level=logging.ERROR,  # Send errors as events.
)


def sentry_init(dsn, traces_sample_rate):
    sentry_sdk.init(
        dsn=dsn,
        integrations=[sentry_logging, DjangoIntegration()],
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=traces_sample_rate,
        # Associate users (ID+email+username+IP) to errors.
        # https://docs.sentry.io/platforms/python/django/
        send_default_pii=True,
        # Filter out sensitive email and username.
        # Unfortunately ip_address cannot be filtered out.
        # https://docs.sentry.io/error-reporting/configuration/filtering/?platform=python
        before_send=strip_sentry_sensitive_data,
        # The alternative solution
        # https://docs.sentry.io/enriching-error-data/additional-data/?platform=python#capturing-the-user
        # only ever works here (without access to `request.user`)
        # and is silently ignored when used in `context_processors.py` to get access to `request.user`.
    )
    ignore_logger("django.security.DisallowedHost")
