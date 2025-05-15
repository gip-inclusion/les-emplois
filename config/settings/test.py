import os

from itou.utils.enums import ItouEnvironment


ITOU_ENVIRONMENT = ItouEnvironment.DEV
os.environ["ITOU_ENVIRONMENT"] = ITOU_ENVIRONMENT

# Inject default redis settings
os.environ["REDIS_URL"] = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
os.environ["REDIS_DB"] = os.getenv("REDIS_DB", "0")

from config.settings.base import *  # noqa: E402,F403


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

HUEY["immediate"] = False  # noqa: F405
HUEY["name"] = "test_pg_huey"  # noqa: F405

cellar_addon_host = os.getenv("CELLAR_ADDON_HOST_TEST")
AWS_S3_ENDPOINT_URL = (
    f"https://{cellar_addon_host}/"
    if cellar_addon_host
    else f"http://{os.getenv('CELLAR_ADDON_HOST', 'localhost:9000')}/"
)
AWS_S3_ACCESS_KEY_ID = os.getenv("CELLAR_ADDON_KEY_ID_TEST", "minioadmin")
AWS_S3_SECRET_ACCESS_KEY = os.getenv("CELLAR_ADDON_SECRET_KEY_TEST", "minioadmin")
# S3 bucket names must be globally unique. CI uses Cellar, so the storage
# bucket name must not exist on all of Cellar.
# https://www.clever-cloud.com/developers/doc/addons/cellar/#name-your-bucket
AWS_STORAGE_BUCKET_NAME = "c1-tests"

PILOTAGE_DATASTORE_S3_ENDPOINT_URL = AWS_S3_ENDPOINT_URL
PILOTAGE_DATASTORE_S3_ACCESS_KEY = AWS_S3_ACCESS_KEY_ID
PILOTAGE_DATASTORE_S3_SECRET_KEY = AWS_S3_SECRET_ACCESS_KEY
PILOTAGE_DATASTORE_S3_BUCKET_NAME = AWS_STORAGE_BUCKET_NAME

API_DATADOG_API_KEY = "abcde"
API_DATADOG_APPLICATION_KEY = "fghij"

API_PARTICULIER_BASE_URL = "https://fake-api-particulier.com/api/"
API_PARTICULIER_TOKEN = "test"

API_SENTRY_BASE_URL = "https://www.sinatra.com"
API_SENTRY_STATS_TOKEN = "stry_xxx"
API_SENTRY_ORG_ID = "gip"

API_UPDOWN_TOKEN = "ro-XXXXXXXX"
API_UPDOWN_CHECK_ID = "blabla"

if os.getenv("DEBUG_SQL_SNAPSHOT"):
    # Mandatory to have detailed stacktrace inside templates
    TEMPLATES[0]["OPTIONS"]["debug"] = True  # noqa: F405

FORCE_PROCONNECT_LOGIN = True  # default behaviour in tests

REQUIRE_OTP_FOR_STAFF = False
