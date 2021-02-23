from .base import *
from ._sentry import sentry_init

ALLOWED_HOSTS = ["127.0.0.1", ".cleverapps.io"]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRESQL_ADDON_DIRECT_HOST"),
        "PORT": os.environ.get("POSTGRESQL_ADDON_DIRECT_PORT"),
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
