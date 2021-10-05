import os

from ._sentry import sentry_init
from .base import *  # noqa: F401,F403


ALLOWED_HOSTS = ["127.0.0.1", ".cleverapps.io"]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRESQL_ADDON_HOST"),
        "PORT": os.environ.get("POSTGRESQL_ADDON_PORT"),
        "NAME": os.environ.get("POSTGRESQL_ADDON_DB"),
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

# Active Elastic APM metrics
# See https://www.elastic.co/guide/en/apm/agent/python/current/configuration.html
INSTALLED_APPS += ["elasticapm.contrib.django"]  # noqa F405

ELASTIC_APM = {
    "ENABLED": os.environ.get("APM_ENABLED", True),
    "SERVICE_NAME": "itou-django",
    "SERVICE_VERSION": os.environ.get("COMMIT_ID", None),
    "SERVER_URL": os.environ.get("APM_SERVER_URL", ""),
    "SECRET_TOKEN": os.environ.get("APM_AUTH_TOKEN", ""),
    "ENVIRONMENT": "review",
    "DJANGO_TRANSACTION_NAME_FROM_ROUTE": True,
    "TRANSACTION_SAMPLE_RATE": 1,
}
FRANCE_CONNECT_BASE_URL = "https://fcp.integ01.dev-franceconnect.fr/api/v1/"
