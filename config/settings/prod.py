from .base import *  # noqa

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

INSTALLED_APPS += ["django_dramatiq_pg"]

ALLOWED_HOSTS = ["itou-prod.cleverapps.io", "inclusion.beta.gouv.fr"]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRESQL_ADDON_DIRECT_HOST"),
        "PORT": os.environ.get("POSTGRESQL_ADDON_DIRECT_PORT"),
        "NAME": os.environ.get("POSTGRESQL_ADDON_DB"),
        "USER": os.environ.get("POSTGRESQL_ADDON_CUSTOM_USER"),
        "PASSWORD": os.environ.get("POSTGRESQL_ADDON_CUSTOM_PASSWORD"),
    }
}

ITOU_ENVIRONMENT = "PROD"
ITOU_PROTOCOL = "https"
ITOU_FQDN = "inclusion.beta.gouv.fr"
ITOU_EMAIL_CONTACT = "contact@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply@inclusion.beta.gouv.fr"

sentry_sdk.init(dsn=os.environ["SENTRY_DSN_PROD"], integrations=[DjangoIntegration()])
ignore_logger("django.security.DisallowedHost")

# Database connection data is overriden, so we must repeat this part:
# ---
DRAMATIQ_BROKER = {**DRAMATIQ_BROKER_BASE,
                   "OPTIONS": {"url": f"postgres://{_DRMTQ_DB['USER']}:{_DRMTQ_DB['PASSWORD']}@{_DRMTQ_DB['HOST']}:{_DRMTQ_DB['PORT']}/{_DRMTQ_DB['NAME']}", }}

DRAMATIQ_REGISTRY = DRAMATIQ_REGISTRY_BASE
