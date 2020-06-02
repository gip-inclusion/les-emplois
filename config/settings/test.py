import logging

from .base import *  # noqa


# `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Prevent calls to external APIs.
API_BAN_BASE_URL = None
API_INSEE_KEY = None
API_INSEE_SECRET = None
API_ESD_KEY = None
API_ESD_SECRET = None

# Disable logging and traceback in unit tests for readability.
# https://docs.python.org/3/library/logging.html#logging.disable
logging.disable(logging.CRITICAL)

BASE_URL = "http://testserver"
