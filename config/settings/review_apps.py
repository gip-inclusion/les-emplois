from .base import *  # noqa

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

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

ITOU_PROTOCOL = "https"
ITOU_FQDN = "staging.inclusion.beta.gouv.fr"
ITOU_EMAIL_CONTACT = "contact+staging@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply+staging@inclusion.beta.gouv.fr"

sentry_sdk.init(dsn=os.environ["SENTRY_DSN_STAGING"], integrations=[DjangoIntegration()])
