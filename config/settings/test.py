import os


ITOU_ENVIRONMENT = "DEV"
os.environ["ITOU_ENVIRONMENT"] = ITOU_ENVIRONMENT

from .base import *  # noqa: E402,F403


SECRET_KEY = "foobar"
ALLOWED_HOSTS = []

# `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

ASP_ITOU_PREFIX = "XXXXX"  # same as in our fixtures
ITOU_PROTOCOL = "http"
ITOU_FQDN = "localhost:8000"

DATABASES["default"]["HOST"] = os.getenv("PGHOST", "127.0.0.1")  # noqa: F405
DATABASES["default"]["PORT"] = os.getenv("PGPORT", "5432")  # noqa: F405
DATABASES["default"]["NAME"] = os.getenv("PGDATABASE", "itou")  # noqa: F405
DATABASES["default"]["USER"] = os.getenv("PGUSER", "postgres")  # noqa: F405
DATABASES["default"]["PASSWORD"] = os.getenv("PGPASSWORD", "password")  # noqa: F405

MAILJET_API_KEY_PRINCIPAL = os.getenv("API_MAILJET_KEY_PRINCIPAL", "API_MAILJET_KEY_PRINCIPAL")
MAILJET_SECRET_KEY_PRINCIPAL = os.getenv("API_MAILJET_SECRET_PRINCIPAL", "API_MAILJET_SECRET_PRINCIPAL")
