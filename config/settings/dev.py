import os
import socket


ITOU_ENVIRONMENT = "DEV"
os.environ["ITOU_ENVIRONMENT"] = ITOU_ENVIRONMENT

from .base import *  # pylint: disable=wildcard-import,unused-wildcard-import,wrong-import-position # noqa: E402,F403


# Django settings
# ---------------
SECRET_KEY = "foobar"

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.0.1", "0.0.0.0"]

ASYNC_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SHOW_TEST_ACCOUNTS_BANNER = True

SESSION_COOKIE_SECURE = False

AUTH_PASSWORD_VALIDATORS = []

INSTALLED_APPS.extend(  # noqa: F405
    [
        "django_extensions",
        "debug_toolbar",
        "django_admin_logs",
    ]
)

INTERNAL_IPS = ["127.0.0.1"]

# `ManifestStaticFilesStorage` (used in base settings) requires `collectstatic` to be run.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Enable django-debug-toolbar with Docker.
# Hack is coming from https://stackoverflow.com/a/45624773
# inspired by https://github.com/cookiecutter/cookiecutter-django/blob/master/%7B%7Bcookiecutter.project_slug%7D%7D/config/settings/local.py#L71 # pylint: disable=line-too-long # noqa: E501
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

ASP_ITOU_PREFIX = "XXXXX"  # same as in our fixtures

ITOU_PROTOCOL = "http"
ITOU_FQDN = "127.0.0.1:8000"

DATABASES["default"]["HOST"] = os.getenv("PGHOST", "127.0.0.1")  # noqa: F405
DATABASES["default"]["PORT"] = os.getenv("PGPORT", "5432")  # noqa: F405
DATABASES["default"]["NAME"] = os.getenv("PGDATABASE", "itou")  # noqa: F405
DATABASES["default"]["USER"] = os.getenv("PGUSER", "postgres")  # noqa: F405
DATABASES["default"]["PASSWORD"] = os.getenv("PGPASSWORD", "password")  # noqa: F405

if SQL_DEBUG:  # noqa: F405
    LOGGING.setdefault("loggers", {})["django.db.backends"] = {  # noqa: F405
        "level": "DEBUG",
        "handlers": ["console"],
        "propagate": False,
    }

# use almost the same settings for metabase as base PG.
METABASE_HOST = os.getenv("PGHOST", "127.0.0.1")  # noqa: F405
METABASE_PORT = os.getenv("PGPORT", "5432")  # noqa: F405
METABASE_USER = os.getenv("PGUSER", "postgres")  # noqa: F405o
METABASE_PASSWORD = os.getenv("PGPASSWORD", "password")  # noqa: F405
METABASE_DATABASE = os.getenv("PGDATABASE", "metabase")  # noqa: F405

MAILJET_API_KEY_PRINCIPAL = os.getenv("API_MAILJET_KEY", "API_MAILJET_KEY")
MAILJET_SECRET_KEY_PRINCIPAL = os.getenv("API_MAILJET_SECRET", "API_MAILJET_SECRET")
