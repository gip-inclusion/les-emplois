import logging

import pytz
from django.utils import timezone

from .base import *  # noqa: F401,F403


# `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Prevent calls to external APIs but keep a valid scheme
API_BAN_BASE_URL = None
API_ENTREPRISE_BASE_URL = "http://example.com"
API_ESD_KEY = None
API_ESD_SECRET = None
API_ENTREPRISE_RECIPIENT = 12345
API_ENTREPRISE_TOKEN = 12345

# Disable logging and traceback in unit tests for readability.
# https://docs.python.org/3/library/logging.html#logging.disable
logging.disable(logging.CRITICAL)

ITOU_ENVIRONMENT = "TEST"
ITOU_PROTOCOL = "http"
ITOU_FQDN = "testserver"

# SIAE stats are always enabled for tests. We do not test the temporary whitelist system.
RELEASE_SIAE_STATS = True

ASP_FS_KNOWN_HOSTS = None

# Employee record production deployment
EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE = timezone.datetime(2021, 1, 1, tzinfo=pytz.UTC)

FRANCE_CONNECT_CLIENT_ID = "FC_CLIENT_ID_123"
FRANCE_CONNECT_CLIENT_SECRET = "FC_CLIENT_SECRET_123"

# Approvals
AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL = "colette@ratatouille.com"
