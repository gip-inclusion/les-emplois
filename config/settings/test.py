import os


ITOU_ENVIRONMENT = "DEV"
os.environ["ITOU_ENVIRONMENT"] = ITOU_ENVIRONMENT

from .base import *  # noqa: E402,F403


SECRET_KEY = "foobar"
ALLOWED_HOSTS = []

# We *want* to do the same `collectstatic` on the CI than on PROD to catch errors early,
# but we don't want to do it when running the test suite locally for performance reasons.
if not os.getenv("CI", False):
    # `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
    STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405

ASP_ITOU_PREFIX = "XXXXX"  # same as in our fixtures
ITOU_PROTOCOL = "http"
ITOU_FQDN = "localhost:8000"

DATABASES["default"]["HOST"] = os.getenv("PGHOST", "127.0.0.1")  # noqa: F405
DATABASES["default"]["PORT"] = os.getenv("PGPORT", "5432")  # noqa: F405
DATABASES["default"]["NAME"] = os.getenv("PGDATABASE", "itou")  # noqa: F405
DATABASES["default"]["USER"] = os.getenv("PGUSER", "postgres")  # noqa: F405
DATABASES["default"]["PASSWORD"] = os.getenv("PGPASSWORD", "password")  # noqa: F405

MAILJET_API_KEY_PRINCIPAL = "API_MAILJET_KEY_PRINCIPAL"
MAILJET_SECRET_KEY_PRINCIPAL = "API_MAILJET_SECRET_PRINCIPAL"

AWS_S3_ENDPOINT_URL = f"http://{os.getenv('CELLAR_ADDON_HOST', 'localhost:9000')}/"
AWS_S3_ACCESS_KEY_ID = "minioadmin"
AWS_S3_SECRET_ACCESS_KEY = "minioadmin"
AWS_STORAGE_BUCKET_NAME = "tests"
