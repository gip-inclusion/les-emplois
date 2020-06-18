from .base import *  # noqa

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

ITOU_FQDN = "demo.inclusion.beta.gouv.fr"
ALLOWED_HOSTS = ["127.0.0.1", ".cleverapps.io", ITOU_FQDN]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRESQL_ADDON_HOST"),
        "PORT": os.environ.get("POSTGRESQL_ADDON_PORT"),
        "NAME": os.environ.get("DEMO_APP_DB_NAME"),
        "USER": os.environ.get("POSTGRESQL_ADDON_USER"),
        "PASSWORD": os.environ.get("POSTGRESQL_ADDON_PASSWORD"),
    }
}

ITOU_PROTOCOL = "https"
ITOU_EMAIL_CONTACT = "contact+demo@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply+demo@inclusion.beta.gouv.fr"

sentry_sdk.init(dsn=os.environ["SENTRY_DSN_DEMO"], integrations=[DjangoIntegration()])
ignore_logger("django.security.DisallowedHost")

ITOU_ENVIRONMENT = "DEMO"
ASP_ITOU_PREFIX = "XXXXX"

# Override allauth DefaultAccountAdapter: provides custom context to email templates
ACCOUNT_ADAPTER = "itou.utils.account_adapter.DemoAccountAdapter"
