import os
import socket


ITOU_ENVIRONMENT = "DEV"
os.environ["ITOU_ENVIRONMENT"] = ITOU_ENVIRONMENT

from .test import *  # noqa: E402,F403


# Django settings
# ---------------
DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.0.1", "0.0.0.0"]

ASYNC_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SHOW_DEMO_ACCOUNTS_BANNER = True

SESSION_COOKIE_SECURE = False

AUTH_PASSWORD_VALIDATORS = []

INSTALLED_APPS.extend(  # noqa: F405
    [
        "django_extensions",
        "debug_toolbar",
    ]
)

INTERNAL_IPS = ["127.0.0.1"]
ITOU_FQDN = "127.0.0.1:8000"  # localhost doesn't work with PEAMU

# Enable django-debug-toolbar with Docker.
# Hack is coming from https://stackoverflow.com/a/45624773
# inspired by https://github.com/cookiecutter/cookiecutter-django/blob/master/%7B%7Bcookiecutter.project_slug%7D%7D/config/settings/local.py#L71 # # noqa: E501
_, _, ips = socket.gethostbyname_ex(socket.gethostname())
INTERNAL_IPS += [".".join(ip.split(".")[:-1] + ["1"]) for ip in ips]

MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa F405
DEBUG_TOOLBAR_CONFIG = {
    # https://django-debug-toolbar.readthedocs.io/en/latest/panels.html#panels
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        # ProfilingPanel makes the django admin extremely slow...
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}


REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] += [  # noqa: F405
    # For DRF browsable API access
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# ITOU settings
# -------------

API_BAN_BASE_URL = os.getenv("API_BAN_BASE_URL", "https://api-adresse.data.gouv.fr")
API_GEO_BASE_URL = os.getenv("API_GEO_BASE_URL", "https://geo.api.gouv.fr")
MATOMO_BASE_URL = os.getenv("MATOMO_BASE_URL", "https://matomo.inclusion.beta.gouv.fr/")
MATOMO_SITE_ID = 220

# use almost the same settings for metabase as base PG.
METABASE_HOST = os.getenv("METABASE_HOST", os.getenv("PGHOST", "127.0.0.1"))  # noqa: F405
METABASE_PORT = os.getenv("METABASE_PORT", os.getenv("PGPORT", "5432"))  # noqa: F405
METABASE_USER = os.getenv("METABASE_USER", os.getenv("PGUSER", "postgres"))  # noqa: F405o
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", os.getenv("PGPASSWORD", "password"))  # noqa: F405
METABASE_DATABASE = os.getenv("METABASE_DATABASE", os.getenv("PGDATABASE", "metabase"))  # noqa: F405

FORCE_IC_LOGIN = os.getenv("FORCE_IC_LOGIN", "True") == "True"

AWS_STORAGE_BUCKET_NAME = "dev"

# Don't use json formatter in dev
del LOGGING["handlers"]["console"]["formatter"]  # noqa: F405
