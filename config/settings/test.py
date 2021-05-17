import logging

from .base import *

# `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Prevent calls to external APIs.
API_BAN_BASE_URL = None
API_ENTREPRISE_BASE_URL = None
API_ESD_KEY = None
API_ESD_SECRET = None

# Disable logging and traceback in unit tests for readability.
# https://docs.python.org/3/library/logging.html#logging.disable
logging.disable(logging.CRITICAL)

ITOU_ENVIRONMENT = "TEST"
ITOU_PROTOCOL = "http"
ITOU_FQDN = "testserver"

ASP_FS_KNOWN_HOSTS = None
