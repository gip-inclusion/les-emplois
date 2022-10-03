import os
import socket


ITOU_ENVIRONMENT = "DEV"
os.environ["ITOU_ENVIRONMENT"] = ITOU_ENVIRONMENT

from .base import *  # pylint: disable=wildcard-import,unused-wildcard-import


# Django settings
# ---------------
SECRET_KEY = "foobar"

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.0.1"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SHOW_TEST_ACCOUNTS_BANNER = True

SESSION_COOKIE_SECURE = False

CSRF_COOKIE_SECURE = False

AUTH_PASSWORD_VALIDATORS = []

INSTALLED_APPS.extend(
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
# inspired by https://github.com/cookiecutter/cookiecutter-django/blob/master/%7B%7Bcookiecutter.project_slug%7D%7D/config/settings/local.py#L71
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


REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] += [
    # For DRF browseable API access
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# ITOU settings
# -------------

ASP_ITOU_PREFIX = "XXXXX"  # same as in our fixtures

ITOU_PROTOCOL = "http"
ITOU_FQDN = "127.0.0.1:8000"

DATABASES["default"]["HOST"] = os.getenv("PGHOST", "127.0.0.1")
DATABASES["default"]["PORT"] = os.getenv("PGPORT", "5432")
DATABASES["default"]["NAME"] = os.getenv("PGDATABASE", "itou")
DATABASES["default"]["USER"] = os.getenv("PGUSER", "postgres")
DATABASES["default"]["PASSWORD"] = os.getenv("PGPASSWORD", "password")

ELASTIC_APM["ENABLED"] = False
# FIXME(vperron): Remove this as soon as the checks are disabled
# followup on https://github.com/elastic/apm-agent-python/pull/1632
ELASTIC_APM["SERVER_URL"] = "http://127.0.0.1"

if os.getenv("SQL_DEBUG", "False") == "True":
    LOGGING.setdefault("loggers", {})["django.db.backends"] = {
        "level": "DEBUG",
        "handlers": ["console"],
        "propagate": False,
    }
