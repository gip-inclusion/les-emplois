from .base import *  # noqa

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

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
ITOU_FQDN = os.environ.get("DEPLOY_URL", "staging.inclusion.beta.gouv.fr")
ITOU_EMAIL_CONTACT = "contact+staging@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply+staging@inclusion.beta.gouv.fr"

SHOW_TEST_ACCOUNTS_BANNER = True

sentry_sdk.init(dsn=os.environ["SENTRY_DSN_STAGING"], integrations=[DjangoIntegration()])
ignore_logger("django.security.DisallowedHost")


# Database connection data is overriden, so we must repeat this part:
# ---
# _DRMTQ_DB = DATABASES[DRAMATIQ_DB_ALIAS]

# DRAMATIQ_BROKER = {
#     "OPTIONS": {
#         "url": f"postgres://{_DRMTQ_DB['USER']}:{_DRMTQ_DB['PASSWORD']}@{_DRMTQ_DB['HOST']}:{_DRMTQ_DB['PORT']}/{_DRMTQ_DB['NAME']}"
#     },
#     "MIDDLEWARE": [
#         "dramatiq.middleware.TimeLimit",
#         "dramatiq.middleware.Callbacks",
#         "dramatiq.middleware.Retries",
#         "dramatiq.results.Results",
#     ],
# }
# DRAMATIQ_REGISTRY = 'itou.utils.actors.REGISTRY'
