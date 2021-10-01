import os

from ._sentry import sentry_init
from .base import *  # noqa: F401,F403


# See `itou.utils.new_dns.middleware.NewDnsRedirectMiddleware`.
ALLOWED_HOSTS = [
    "itou-prod.cleverapps.io",
    "inclusion.beta.gouv.fr",
    "emploi.inclusion.beta.gouv.fr",
    "emplois.inclusion.beta.gouv.fr",
]

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
ITOU_FQDN = "emplois.inclusion.beta.gouv.fr"
ITOU_EMAIL_CONTACT = "contact@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply@inclusion.beta.gouv.fr"

sentry_init(dsn=os.environ["SENTRY_DSN_PROD"])

ALLOW_POPULATING_METABASE = True

# DRF Browseable API renderer is not available in production
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = ["rest_framework.renderers.JSONRenderer"]  # noqa F405

# Active Elastic APM metrics
# See https://www.elastic.co/guide/en/apm/agent/python/current/configuration.html
INSTALLED_APPS += ["elasticapm.contrib.django"]  # noqa F405

ELASTIC_APM = {
    "ENABLED": os.environ.get("APM_ENABLED", True),
    "SERVICE_NAME": "itou-django",
    "SERVICE_VERSION": os.environ.get("COMMIT_ID", None),
    "SERVER_URL": os.environ.get("APM_SERVER_URL", ""),
    "SECRET_TOKEN": os.environ.get("APM_AUTH_TOKEN", ""),
    "ENVIRONMENT": "prod",
    "DJANGO_TRANSACTION_NAME_FROM_ROUTE": True,
    "TRANSACTION_SAMPLE_RATE": 0.1,
}
