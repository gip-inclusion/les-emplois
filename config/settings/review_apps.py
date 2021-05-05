from ._sentry import sentry_init
from .base import *


ALLOWED_HOSTS = ["127.0.0.1", ".cleverapps.io"]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRESQL_ADDON_HOST"),
        "PORT": os.environ.get("POSTGRESQL_ADDON_PORT"),
        "NAME": os.environ.get("REVIEW_APP_DB_NAME"),
        "USER": os.environ.get("POSTGRESQL_ADDON_USER"),
        "PASSWORD": os.environ.get("POSTGRESQL_ADDON_PASSWORD"),
    }
}

ITOU_ENVIRONMENT = "REVIEW_APP"
ITOU_PROTOCOL = "https"
ITOU_FQDN = os.environ.get("DEPLOY_URL", "staging.emplois.inclusion.beta.gouv.fr")
ITOU_EMAIL_CONTACT = "contact+staging@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply+staging@inclusion.beta.gouv.fr"

# Use a sync email backend.
EMAIL_BACKEND = "anymail.backends.mailjet.EmailBackend"

sentry_init(dsn=os.environ["SENTRY_DSN_STAGING"])

SHOW_TEST_ACCOUNTS_BANNER = True

# S3 uploads
# ------------------------------------------------------------------------------
S3_STORAGE_ACCESS_KEY_ID = os.environ.get("CELLAR_ADDON_KEY_ID", "")
S3_STORAGE_SECRET_ACCESS_KEY = os.environ.get("CELLAR_ADDON_KEY_SECRET", "")
S3_STORAGE_ENDPOINT_DOMAIN = os.environ.get("CELLAR_ADDON_HOST", "")

S3_STORAGE_BASE_ENDPOINT_URL = "https://%s" % S3_STORAGE_ENDPOINT_DOMAIN
S3_STORAGE_BUCKET_ENDPOINT_URL = "https://%s.%s" % (S3_STORAGE_BUCKET_NAME, S3_STORAGE_ENDPOINT_DOMAIN)
