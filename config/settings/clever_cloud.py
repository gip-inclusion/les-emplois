from .base import *  # noqa

DEBUG = os.environ.get("DJANGO_DEBUG", True)

ALLOWED_HOSTS = ["127.0.0.1", ".cleverapps.io"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Django-extensions.
# ------------------------------------------------------------------------------

INSTALLED_APPS += ["django_extensions"]  # noqa F405

# Django-debug-toolbar.
# ------------------------------------------------------------------------------

INSTALLED_APPS += ["debug_toolbar"]  # noqa F405

INTERNAL_IPS = ["127.0.0.1"]

# Enable django-debug-toolbar with Docker.
import socket

_, _, ips = socket.gethostbyname_ex(socket.gethostname())
INTERNAL_IPS += [ip[:-1] + "1" for ip in ips]

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

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

DB_SCHEMA = os.environ.get("REVIEW_APP_DB_SCHEMA")
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRESQL_ADDON_HOST"),
        "PORT": os.environ.get("POSTGRESQL_ADDON_PORT"),
        "NAME": os.environ.get("POSTGRESQL_ADDON_DB"),
        "USER": os.environ.get("POSTGRESQL_ADDON_USER"),
        "PASSWORD": os.environ.get("POSTGRESQL_ADDON_PASSWORD"),
        'OPTIONS': {
            'options': f'-c search_path={DB_SCHEMA},public',
        },
    }
}
