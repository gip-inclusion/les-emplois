import logging

from django.utils import timezone

from .base import *  # noqa: F401,F403


# `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Prevent calls to external APIs but keep a valid scheme
API_BAN_BASE_URL = None
API_ENTREPRISE_BASE_URL = "http://example.com"
API_ENTREPRISE_TOKEN = 12345
API_ENTREPRISE_RECIPIENT = 12345

# Don't show logs and traceback in unit tests for readability.
LOGGING = {
    "version": 1,
    "handlers": {
        "null": {"class": "logging.NullHandler"},
    },
    "root": {
        "handlers": ["null"],
    },
}


ITOU_ENVIRONMENT = "TEST"
ITOU_PROTOCOL = "http"
ITOU_FQDN = "testserver"

# SIAE stats are always enabled for tests. We do not test the temporary whitelist system.
RELEASE_STATS_SIAE = True

ASP_FS_KNOWN_HOSTS = None

# Employee record production deployment
EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE = timezone.datetime(2021, 1, 1, tzinfo=timezone.utc)
# Allow for testing
EMPLOYEE_RECORD_TRANSFER_ENABLED = True

FRANCE_CONNECT_CLIENT_ID = "FC_CLIENT_ID_123"
FRANCE_CONNECT_CLIENT_SECRET = "FC_CLIENT_SECRET_123"

# Approvals
AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL = "colette@ratatouille.com"

# We override those urls in test in order to ensure that, should everything go wrong, we do not send stuff to
# PE’s production databases
# API_ESD["AUTH_BASE_URL"] = "https://some-authentication-domain.fr"  # noqa F405
# API_ESD["BASE_URL"] = "https://some-base-domain.fr/partenaire"  # noqa F405

# Leave any uploaded files appear legit as soon as they are hosted on "server.com"
# The developer then does not need to worry about any resume link using this domain,
# or computed from the factories (which also use it)
# Override it in the tests only when you explicitly want to test a failure.
S3_STORAGE_ENDPOINT_DOMAIN = "server.com"
