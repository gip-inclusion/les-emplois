from .base import *  # noqa

# `CachedStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Prevent calls to external APIs.
API_BAN_BASE_URL = None
API_INSEE_KEY = None
API_INSEE_SECRET = None
API_EMPLOI_STORE_KEY = None
API_EMPLOI_STORE_SECRET = None
