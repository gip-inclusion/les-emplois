"""
Base settings to build other settings files upon.
https://docs.djangoproject.com/en/dev/ref/settings
"""

import datetime
import json
import os
import re
import warnings

import csp.constants
from botocore.config import Config
from dotenv import load_dotenv

from config.sentry import sentry_init
from itou.common_apps.address.departments import REGIONS
from itou.utils.enums import ItouEnvironment
from itou.utils.urls import markdown_url_set_protocol, markdown_url_set_target_blank


load_dotenv()

# Django settings
# ---------------

_current_dir = os.path.dirname(os.path.realpath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(_current_dir, "../.."))

APPS_DIR = os.path.abspath(os.path.join(ROOT_DIR, "itou"))
FIXTURE_DIRS = [os.path.abspath(os.path.join(ROOT_DIR, "itou/fixtures/django"))]

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")

DEBUG = False

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "inclusion.beta.gouv.fr,emplois.inclusion.beta.gouv.fr").split(",")

SITE_ID = 1

INSTALLED_APPS = [
    # Django apps.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.gis",
    "django.contrib.postgres",
    "django.contrib.humanize",
    "django.forms",  # Required to override default Django widgets. See FORM_RENDERER
    # Third party apps.
    "anymail",
    "citext",
    "csp",
    "django_bootstrap5",
    "django_select2",
    "formtools",
    "huey.contrib.djhuey",
    "markdownify",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "django_filters",
    "django_htmx",
    "hijack",
    "hijack.contrib.admin",
    "pgtrigger",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "slippers",
    # Register adapters before to load allauth apps.
    "itou.allauth_adapters",
    "allauth",
    "allauth.account",
    # ITOU apps.
    "itou.utils",
    "itou.cities",
    "itou.companies",
    "itou.emails",
    "itou.jobs",
    "itou.users",
    "itou.prescribers",
    "itou.institutions",
    "itou.files",
    "itou.job_applications",
    "itou.approvals",
    "itou.eligibility",
    "itou.openid_connect.france_connect",
    "itou.openid_connect.pe_connect",
    "itou.openid_connect.pro_connect",
    "itou.otp",
    "itou.invitations",
    "itou.external_data",
    "itou.metabase",
    "itou.asp",
    "itou.employee_record",
    "itou.siae_evaluations",
    "itou.geiq_assessments",
    "itou.geo",
    "itou.search",
    "itou.www.apply",
    "itou.www.approvals_views",
    "itou.www.autocomplete",
    "itou.www.dashboard",
    "itou.www.eligibility_views",
    "itou.www.employees_views",
    "itou.www.geiq_assessments_views",
    "itou.www.home",
    "itou.www.prescribers_views",
    "itou.www.search_views",
    "itou.www.companies_views",
    "itou.www.signup",
    "itou.www.invitations_views",
    "itou.www.stats",
    "itou.www.welcoming_tour",
    "itou.www.employee_record_views",
    "itou.www.siae_evaluations_views",
    "itou.api",
    "itou.antivirus",
    "itou.scripts",
    "itou.analytics",
    "itou.communications",
    "itou.gps",
    "itou.rdv_insertion",
    "itou.archive",
    "itou.nexus",
]

# TODO: Remove with Django 6.0
warnings.filterwarnings("ignore", "The FORMS_URLFIELD_ASSUME_HTTPS transitional setting is deprecated.")
FORMS_URLFIELD_ASSUME_HTTPS = True

MIDDLEWARE = [
    # Generate request Id
    "django_datadog_logger.middleware.request_id.RequestIdMiddleware",
    # Itou health check for Clever Cloud, don’t require requests to match ALLOWED_HOSTS
    "itou.www.middleware.public_health_check",
    # Django stack
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Maintenance: if enabled we will skip all the remaning middlewares
    "itou.www.middleware.maintenance",
    # Django stack again
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Third party
    "allauth.account.middleware.AccountMiddleware",
    "csp.middleware.CSPMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "hijack.middleware.HijackUserMiddleware",
    "django_otp.middleware.OTPMiddleware",
    # Itou specific
    "itou.utils.perms.middleware.ItouCurrentOrganizationMiddleware",
    "itou.www.middleware.never_cache",
    "itou.www.middleware.RateLimitMiddleware",
    "itou.openid_connect.pro_connect.middleware.ProConnectLoginMiddleware",
    "itou.utils.triggers.middleware.fields_history",
    # Final logger
    "django_datadog_logger.middleware.request_log.RequestLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(APPS_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                # Django CSP
                "csp.context_processors.nonce",
                # Itou.
                "itou.utils.settings_context_processors.expose_settings",
                "itou.utils.context_processors.matomo",
                "itou.utils.context_processors.active_announcement_campaign",
            ],
            "builtins": ["slippers.templatetags.slippers"],
        },
    }
]

# Override default Django forms widgets templates.
# Requires django.forms in INSTALLED_APPS
# https://timonweb.com/django/overriding-field-widgets-in-django-doesnt-work-template-not-found-the-solution/
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

try:
    # This module is only available when running under uWSGI
    # https://uwsgi-docs.readthedocs.io/en/latest/PythonModule.html
    import uwsgi  # noqa: F401
except ImportError:
    db_statement_timeout = int(os.environ.get("SCRIPT_DB_STATEMENT_TIMEOUT", 300_000))
    db_lock_timeout = int(os.environ.get("SCRIPT_DB_LOCK_TIMEOUT", 150_000))
else:
    db_statement_timeout = int(os.environ.get("WWW_DB_STATEMENT_TIMEOUT", 10_000))
    db_lock_timeout = int(os.environ.get("WWW_DB_LOCK_TIMEOUT", 5_000))

DATABASES = {
    "default": {
        "ATOMIC_REQUESTS": True,
        # Since we have the health checks enabled, no need to define a max age:
        # if the connection was closed on the database side, the check will detect it
        "CONN_MAX_AGE": None,
        "CONN_HEALTH_CHECKS": True,
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.getenv("POSTGRESQL_ADDON_DB"),
        # The custom iptables rules forces us to use the direct host and port in production, the
        # usual one is unreachable.
        "HOST": os.getenv("POSTGRESQL_ADDON_DIRECT_HOST"),
        "PORT": os.getenv("POSTGRESQL_ADDON_DIRECT_PORT"),
        "USER": os.getenv("POSTGRESQL_ADDON_USER"),
        "PASSWORD": os.getenv("POSTGRESQL_ADDON_PASSWORD"),
        "OPTIONS": {
            "connect_timeout": 5,
            "options": f"-c statement_timeout={db_statement_timeout} -c lock_timeout={db_lock_timeout}",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

PASSWORD_MIN_LENGTH = 14
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "itou.utils.password_validation.CnilCompositionPasswordValidator"},
]

LANGUAGE_CODE = "fr-FR"

TIME_ZONE = "Europe/Paris"

USE_I18N = True

USE_TZ = True

DATE_INPUT_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d %m %Y"]

STATIC_ROOT = os.path.join(APPS_DIR, "static_collected")

STATIC_URL = "/static/"

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "public": {
        "BACKEND": "itou.utils.storage.s3.PublicStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

STATICFILES_FINDERS = (
    "itou.utils.staticfiles.DownloadAndVendorStaticFilesFinder",
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
)

STATICFILES_DIRS = (os.path.join(APPS_DIR, "static"),)

CSRF_USE_SESSIONS = True

SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SECURE = True

# Force browser to end session when closing.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Since some browser restore session when restarting, the previous setting may not
# work as we want. This is why we ask Django to expire sessions in DB after 1 week
# of inactivity.
# -> https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies#define_the_lifetime_of_a_cookie
# In addition, the command shorten_active_sessions is run every week to force user to connect at least once per week
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7

SESSION_SERIALIZER = "itou.utils.session.JSONSerializer"

X_FRAME_OPTIONS = "DENY"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "httpx_filter": {"()": "itou.utils.logging.HTTPXFilter"},
    },
    "formatters": {
        "json": {"()": "itou.utils.logging.ItouDataDogJSONFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
        "null": {"class": "logging.NullHandler"},
    },
    "loggers": {
        "": {"handlers": ["console"], "level": "INFO"},
        "django": {
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
        },
        # Silence `Invalid HTTP_HOST header` errors.
        # This should be done at the HTTP server level when possible.
        # https://docs.djangoproject.com/en/3.0/topics/logging/#django-security
        "django.security.DisallowedHost": {
            "handlers": ["null"],
            "propagate": False,
        },
        "itou": {
            "level": os.getenv("ITOU_LOG_LEVEL", "INFO"),
        },
        # Logger for DRF API application
        # Will be "log-drained": may need to adjust format
        "api_drf": {
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
        },
        # Huey; async tasks
        "huey": {
            "level": os.getenv("HUEY_LOG_LEVEL", "WARNING"),
            # Define a null handler to prevent huey from adding a StreamHandler:
            # https://github.com/coleifer/huey/blob/2.5.2/huey/contrib/djhuey/management/commands/run_huey.py#L87-L88
            # We'll still get the logs since they will propagate to root handlers
            "handlers": ["null"],
        },
        "httpx": {
            "filters": ["httpx_filter"],
        },
    },
}

DJANGO_DATADOG_LOGGER_EXTRA_INCLUDE = re.compile(
    r"""
    ^(
        django_datadog_logger\.middleware\.request_log  # Built-in datadog logger.
        |itou(\..+)?  # Itou root logger and children.
    )$""",
    re.VERBOSE,
)

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

SILENCED_SYSTEM_CHECKS = ["slippers.E001"]  # We register the components differently

# User authentication callbacks such as redirections after login.
# Replaces LOGIN_REDIRECT_URL, which is static, by ACCOUNT_ADAPTER which is dynamic.
# https://django-allauth.readthedocs.io/en/latest/advanced.html#custom-redirects
ACCOUNT_ADAPTER = "itou.users.adapter.UserAdapter"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_CHANGE_EMAIL = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_USER_DISPLAY = "itou.users.models.get_allauth_account_user_display"

BOOTSTRAP5 = {
    "required_css_class": "form-group-required",
    "wrapper_class": "form-group",
    "error_css_class": "is-invalid",
    "set_placeholder": False,
}

SELECT2_THEME = "bootstrap-5"

# ITOU settings
# -------------


ITOU_ENVIRONMENT = ItouEnvironment(os.getenv("ITOU_ENVIRONMENT", ItouEnvironment.PROD))
ITOU_PROTOCOL = "https"
ITOU_FQDN = os.getenv("ITOU_FQDN", "emplois.inclusion.beta.gouv.fr")
ITOU_EMAIL_CONTACT = os.getenv("ITOU_EMAIL_CONTACT", "assistance@inclusion.beta.gouv.fr")
PILOTAGE_INSTITUTION_EMAIL_CONTACT = os.getenv(
    "PILOTAGE_INSTITUTION_EMAIL_CONTACT", "pilotage+institution@inclusion.gouv.fr"
)
API_EMAIL_CONTACT = os.getenv("API_EMAIL_CONTACT", "api.emplois@inclusion.gouv.fr")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@inclusion.beta.gouv.fr")

# Sentry
# Expose the value through the settings_viewer app.
SENTRY_DSN = os.getenv("SENTRY_DSN")
sentry_init()

SHOW_DEMO_ACCOUNTS_BANNER = ITOU_ENVIRONMENT in (
    ItouEnvironment.DEMO,
    ItouEnvironment.PENTEST,
    ItouEnvironment.REVIEW_APP,
)

# https://adresse.data.gouv.fr/faq
API_BAN_BASE_URL = os.getenv("API_BAN_BASE_URL")

# https://api.gouv.fr/api/api-geo.html#doc_tech
API_GEO_BASE_URL = os.getenv("API_GEO_BASE_URL")

# https://portail-api.insee.fr/catalog/all
API_INSEE_AUTH_URL = os.getenv("API_INSEE_AUTH_URL")
API_INSEE_CLIENT_ID = os.getenv("API_INSEE_CLIENT_ID")
API_INSEE_CLIENT_SECRET = os.getenv("API_INSEE_CLIENT_SECRET")
API_INSEE_USERNAME = os.getenv("API_INSEE_USERNAME")
API_INSEE_PASSWORD = os.getenv("API_INSEE_PASSWORD")
# https://portail-api.insee.fr/catalog/api/26d13266-689d-3fee-845d-c08e12b8f0dd/doc?page=4a0ebed4-14e5-4520-8ebe-d414e5e52004
# This link requires to login : click on Sign-in > CONNEXION-POUR-LES-EXTERNES and use the credentials in Bitwarden
API_INSEE_SIRENE_URL = os.getenv("API_INSEE_SIRENE_URL")
API_INSEE_METADATA_URL = os.getenv("API_INSEE_METADATA_URL")

API_DATA_INCLUSION_BASE_URL = os.getenv("API_DATA_INCLUSION_BASE_URL")
API_DATA_INCLUSION_TOKEN = os.getenv("API_DATA_INCLUSION_TOKEN")
API_DATA_INCLUSION_SOURCES = os.getenv("API_DATA_INCLUSION_SOURCES")
API_DATA_INCLUSION_SCORE_QUALITE_MINIMUM = os.getenv("API_DATA_INCLUSION_SCORE_QUALITE_MINIMUM", 0.6)

API_GEIQ_LABEL_BASE_URL = os.getenv("API_GEIQ_LABEL_BASE_URL")
API_GEIQ_LABEL_TOKEN = os.getenv("API_GEIQ_LABEL_TOKEN")
GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = (
    env_val.split(",") if (env_val := os.getenv("GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES", "")) else []
)

# Pôle emploi's Emploi Store Dev aka ESD. There is a production AND a recette environment.
# Key and secrets are stored on pole-emploi.io (prod and recette) accounts, the values are not the
# same depending on the environment
# Please note that some of APIs have a dry run mode which is handled through (possibly undocumented) scopes
API_ESD = {
    "AUTH_BASE_URL_PARTENAIRE": os.getenv("API_ESD_AUTH_BASE_URL_PARTENAIRE"),
    "KEY": os.getenv("API_ESD_KEY"),
    "SECRET": os.getenv("API_ESD_SECRET"),
    "BASE_URL": os.getenv("API_ESD_BASE_URL"),
}

# PE Connect aka PEAMU - technically one of ESD's APIs.
# PEAM stands for Pôle emploi Access Management.
# Technically there are two PEAM distinct systems:
# - PEAM "Entreprise", PEAM-E or PEAME for short.
# - PEAM "Utilisateur", PEAM-U or PEAMU for short.
# To avoid confusion between the two when contacting ESD support,
# we get the habit to always explicitely state that we are using PEAM*U*.
PEAMU_AUTH_BASE_URL = os.getenv("PEAMU_AUTH_BASE_URL")

# France Connect https://partenaires.franceconnect.gouv.fr/
FRANCE_CONNECT_BASE_URL = os.getenv("FRANCE_CONNECT_BASE_URL")
FRANCE_CONNECT_CLIENT_ID = os.getenv("FRANCE_CONNECT_CLIENT_ID")
FRANCE_CONNECT_CLIENT_SECRET = os.getenv("FRANCE_CONNECT_CLIENT_SECRET")

PRO_CONNECT_BASE_URL = os.getenv("PRO_CONNECT_BASE_URL")
PRO_CONNECT_CLIENT_ID = os.getenv("PRO_CONNECT_CLIENT_ID")
PRO_CONNECT_CLIENT_SECRET = os.getenv("PRO_CONNECT_CLIENT_SECRET")
PRO_CONNECT_FT_IDP_HINT = os.getenv("PRO_CONNECT_FT_IDP_HINT")

TALLY_URL = os.getenv("TALLY_URL")

# Embedding signed Metabase dashboard
METABASE_SITE_URL = os.getenv("METABASE_SITE_URL")
METABASE_SECRET_KEY = os.getenv("METABASE_SECRET_KEY")
METABASE_API_KEY = os.getenv("METABASE_API_KEY")

ASP_ITOU_PREFIX = "99999"

# Only ACIs given by Convergence France may access some contracts
ACI_CONVERGENCE_SIRET_WHITELIST = json.loads(os.getenv("ACI_CONVERGENCE_SIRET_WHITELIST", "[]"))

# Specific experimental stats are progressively being deployed to more and more users and/or companies.
# Kept as a setting to not let User pks or Company asp_ids in clear in the code.
STATS_SIAE_USER_PK_WHITELIST = json.loads(os.getenv("STATS_SIAE_USER_PK_WHITELIST", "[]"))

# Slack notifications sent by Metabase cronjobs.
SLACK_CRON_WEBHOOK_URL = os.getenv("SLACK_CRON_WEBHOOK_URL")

# Slack notifications sent by check_inconsistencies cronjobs.
SLACK_INCONSISTENCIES_WEBHOOK_URL = os.getenv("SLACK_INCONSISTENCIES_WEBHOOK_URL")

# Production instances (`PROD`, `DEMO`, `PENTEST`, ...) share the same redis but different DB
redis_url = os.environ["REDIS_URL"]
redis_db = os.environ["REDIS_DB"]
redis_common_django_settings = {
    "BACKEND": "itou.utils.cache.UnclearableCache",
    "LOCATION": f"{redis_url}?db={redis_db}",
    "KEY_PREFIX": "django",
}

CACHES = {
    "default": {
        **redis_common_django_settings,
    },
    "failsafe": {
        **redis_common_django_settings,
        "OPTIONS": {
            "CLIENT_CLASS": "itou.utils.cache.FailSafeRedisCacheClient",
        },
    },
    "stats": {
        **redis_common_django_settings,
        "KEY_PREFIX": "stats",
        "TIMEOUT": 42 * 24 * 3600,  # Use a long (but not infinite) timeout to not handle deprecated keys ourselves
        "OPTIONS": {
            "CLIENT_CLASS": "itou.utils.cache.FailSafeRedisCacheClient",
        },
    },
}

HUEY = {
    # Use value from CleverCloud deployment config, or a value per REVIEW-APP.
    "name": os.getenv("HUEY_QUEUE_NAME", DATABASES["default"]["NAME"]),
    # Don't store task results (see our Redis Post-Morten in documentation for more information)
    "results": False,
    "url": f"{redis_url}/?db={redis_db}",
    "consumer": {
        "workers": 2,
        "worker_type": "thread",
    },
}

# Email https://anymail.readthedocs.io/en/stable/esps/mailjet/
ANYMAIL = {
    # it's the default but our probes need this at import time.
    "MAILJET_API_URL": "https://api.mailjet.com/v3.1/",
    "MAILJET_API_KEY": os.getenv("API_MAILJET_KEY_APP"),
    "MAILJET_SECRET_KEY": os.getenv("API_MAILJET_SECRET_APP"),
}

EMAIL_BACKEND = "itou.emails.tasks.AsyncEmailBackend"
# This is the "real" email backend used by the async wrapper / email backend
ASYNC_EMAIL_BACKEND = "anymail.backends.mailjet.EmailBackend"

SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS = 5 * 60
SEND_EMAIL_RETRY_TOTAL_TIME_IN_SECONDS = 24 * 3600

REST_FRAMEWORK = {
    # Namespace versioning e.g. `GET /api/v1/something/`.
    # https://www.django-rest-framework.org/api-guide/versioning/#namespaceversioning
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    # Pagination.
    # https://www.django-rest-framework.org/api-guide/pagination/#pagenumberpagination
    "DEFAULT_PAGINATION_CLASS": "itou.api.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Response renderers
    # See DEV configuration for an additional rendeder for DRF browseable API
    # https://www.django-rest-framework.org/api-guide/renderers/#custom-renderers
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Default permissions for API views: user must be authenticated
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Throttling:
    # See: https://www.django-rest-framework.org/api-guide/throttling/
    "DEFAULT_THROTTLE_CLASSES": [
        "itou.api.throttling.FailSafeAnonRateThrottle",
        "itou.api.throttling.FailSafeUserRateThrottle",
    ],
    # Default values for throttling rates:
    # - overridden in custom throttling classes,
    # - arbitrary values, update should the need arise.
    "DEFAULT_THROTTLE_RATES": {
        "anon": "12/minute",
        "user": "120/minute",
        "job-applications-search": "120/minute",
    },
    "EXCEPTION_HANDLER": "itou.api.errors.custom_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "API - Les emplois de l'inclusion",
    "DESCRIPTION": "Documentation de l'API **emplois.inclusion.beta.gouv.fr**",
    "VERSION": "1.0.0",
    "ENUM_NAME_OVERRIDES": {
        "Civilite": "itou.users.enums.Title",
        "NiveauQualificationEnum": "itou.api.geiq.serializers.LabelEducationLevel",
        "CompanyKindEnum": "itou.companies.enums.CompanyKind",
        "PrescriberOrganizationKindEnum": "itou.prescribers.enums.PrescriberOrganizationKind",
    },
    # Allows to document the choices of a field even if the serializer has allow_null=True.
    # cf. https://github.com/tfranzel/drf-spectacular/issues/235
    "ENUM_ADD_EXPLICIT_BLANK_NULL_CHOICE": False,
    "AUTHENTICATION_WHITELIST": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
}

# Requests default timeout is None... See https://blog.mathieu-leplatre.info/handling-requests-timeout-in-python.html
# Use `httpx`, which has a default timeout of 5 seconds, when possible.
# Otherwise, set a timeout like this:
# requests.get(timeout=settings.REQUESTS_TIMEOUT)
REQUESTS_TIMEOUT = 5  # in seconds

# Markdownify settings
# ------------------------------------------------------------------------------
MARKDOWNIFY = {
    "default": {
        "WHITELIST_TAGS": ["a", "p", "ul", "ol", "li", "em", "strong", "br"],
        "MARKDOWN_EXTENSIONS": ["nl2br", "sane_lists"],
        "LINKIFY_TEXT": {
            "PARSE_URLS": True,
            "CALLBACKS": [markdown_url_set_target_blank, markdown_url_set_protocol],
            "PARSE_EMAIL": True,
        },
    }
}
# ASP SFTP connection
# ------------------------------------------------------------------------------
ASP_SFTP_HOST = os.getenv("ASP_SFTP_HOST")
ASP_SFTP_PORT = int(os.getenv("ASP_SFTP_PORT", "22"))
ASP_SFTP_USER = os.getenv("ASP_SFTP_USER")
# Path to SSH keypair for SFTP connection
ASP_SFTP_PRIVATE_KEY_PATH = os.getenv("ASP_SFTP_PRIVATE_KEY_PATH")
ASP_SFTP_KNOWN_HOSTS = os.getenv("ASP_SFTP_KNOWN_HOSTS")

# ASP data archive passwords
ASP_EA2_UNZIP_PASSWORD = os.getenv("ASP_EA2_UNZIP_PASSWORD")

# S3 uploads
# ------------------------------------------------------------------------------
# django-storages
AWS_S3_ACCESS_KEY_ID = os.getenv("CELLAR_ADDON_KEY_ID")
AWS_S3_SECRET_ACCESS_KEY = os.getenv("CELLAR_ADDON_KEY_SECRET")
AWS_STORAGE_BUCKET_NAME = os.getenv("S3_STORAGE_BUCKET_NAME")
# CleverCloud S3 implementation does not support recent data integrity features from AWS.
# https://github.com/boto/boto3/issues/4392
# https://github.com/boto/boto3/issues/4398#issuecomment-2619946229
AWS_S3_CLIENT_CONFIG = Config(
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)

# The maximum amount of memory (in bytes) a file can take up before being rolled over into a temporary file on disk.
# Picked 5 MB, the max size for a resume. Keep it fast for files under that size, and avoid filling up the RAM.
AWS_S3_MAX_MEMORY_SIZE = 5 * 1024 * 1024
AWS_S3_FILE_OVERWRITE = False
AWS_S3_REGION_NAME = "eu-west-3"
AWS_S3_ENDPOINT_URL = f"https://{os.getenv('CELLAR_ADDON_HOST')}/"

HIJACK_PERMISSION_CHECK = "itou.utils.perms.user.has_hijack_perm"
# Replaced by ACCOUNT_ADAPTER (see above) for general purpose. We still need it to redirect after hijack
LOGIN_REDIRECT_URL = "/dashboard/"

EXPORT_DIR = os.getenv("SCRIPT_EXPORT_PATH", f"{ROOT_DIR}/exports")
IMPORT_DIR = os.getenv("SCRIPT_IMPORT_PATH", f"{ROOT_DIR}/imports")
ASP_FLUX_IAE_DIR = os.getenv("ASP_FLUX_IAE_DIR")

MATOMO_BASE_URL = os.getenv("MATOMO_BASE_URL")
MATOMO_SITE_ID = os.getenv("MATOMO_SITE_ID")
MATOMO_AUTH_TOKEN = os.getenv("MATOMO_AUTH_TOKEN")

# Content Security Policy
# Beware, some browser extensions may prevent the reports to be sent to sentry with CORS errors.
csp_img_src = [
    csp.constants.SELF,
    "data:",  # Because of tarteaucitron.js and bootstrap5
    # OpenStreetMap tiles for django admin maps: both tile. and *.tile are used
    "https://tile.openstreetmap.org",
    "https://*.tile.openstreetmap.org",
    "*.hotjar.com",
    "https://cdn.redoc.ly",
    f"{AWS_S3_ENDPOINT_URL}{AWS_STORAGE_BUCKET_NAME}/news-images/",
]
csp_script_src = [
    csp.constants.SELF,
    csp.constants.NONCE,
    "https://stats.inclusion.beta.gouv.fr",
    "*.hotjar.com",
    "https://tally.so",
]
csp_connect_src = [
    csp.constants.SELF,
    "*.sentry.io",  # Allow to send reports to sentry without CORS errors.
    "*.hotjar.com",
    "*.hotjar.io",
    "wss://*.hotjar.com",
]

if MATOMO_BASE_URL:
    csp_img_src.append(MATOMO_BASE_URL)
    csp_script_src.append(MATOMO_BASE_URL)
    csp_connect_src.append(MATOMO_BASE_URL)

if API_BAN_BASE_URL:
    csp_connect_src.append(API_BAN_BASE_URL)

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "base-uri": [csp.constants.NONE],  # We don't use any <base> element in our code, so let's forbid it
        "connect-src": csp_connect_src,
        "default-src": [csp.constants.SELF],
        "font-src": [
            csp.constants.SELF,
            # '*' does not allows 'data:' fonts
            "data:",  # Because of tarteaucitron.js
        ],
        "frame-ancestors": [
            "https://pilotage.inclusion.beta.gouv.fr",
        ],
        "frame-src": [
            "https://app.livestorm.co",  # Upcoming events from the homepage
            "*.hotjar.com",
            # For stats/pilotage views
            "https://tally.so",
            "https://stats.inclusion.beta.gouv.fr",
            "https://pilotage.inclusion.beta.gouv.fr",
            "https://communaute.inclusion.gouv.fr",
            "https://inclusion.beta.gouv.fr",
            "blob:",  # For downloading Metabase questions as CSV/XSLX/JSON on Firefox etc
            "data:",  # For downloading Metabase questions as PNG on Firefox etc
        ],
        "img-src": csp_img_src,
        "object-src": [csp.constants.NONE],
        "report-uri": os.getenv("CSP_REPORT_URI", None),
        "script-src": csp_script_src,
        # Some browsers don't seem to fallback on script-src if script-src-elem is not there
        # But some other don't support script-src-elem... just copy one into the other
        "script-src-elem": csp_script_src,
        "style-src": [
            csp.constants.SELF,
            # It would be better to whilelist styles hashes but it's to much work for now.
            csp.constants.UNSAFE_INLINE,
        ],
        "worker-src": [
            csp.constants.SELF,
            "blob:",  # Redoc seems to use blob:https://emplois.inclusion.beta.gouv.fr/some-ran-dom-uu-id
        ],
    }
}

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL")

FORCE_PROCONNECT_LOGIN = os.getenv("FORCE_PROCONNECT_LOGIN", "True") == "True"

C4_TOKEN = os.getenv("C4_TOKEN", None)

DORA_BASE_URL = os.getenv("DORA_BASE_URL", "https://dora.inclusion.beta.gouv.fr")

# GPS
# ------------------------------------------------------------------------------
GPS_GROUPS_CREATED_BY_EMAIL = os.getenv("GPS_GROUPS_CREATED_BY_EMAIL", None)
GPS_GROUPS_CREATED_AT_DATE = datetime.date(2024, 6, 12)
GPS_NAV_ENTRY_DEPARTMENTS = ["30"]
GPS_SLACK_WEBHOOK_URL = os.getenv("GPS_SLACK_WEBHOOK_URL")
GPS_CONTACT_EMAIL = "contact.gps@inclusion.gouv.fr"

# Afpa
AFPA_DEPARTMENTS = [
    department
    for region in [
        "Auvergne-Rhône-Alpes",
        "Bretagne",
        "Nouvelle-Aquitaine",
        "Occitanie",
        "Provence-Alpes-Côte d'Azur",
    ]
    for department in REGIONS[region]
]

# Mon récap
# ------------------------------------------------------------------------------
MON_RECAP_BANNER_DEPARTMENTS = ["59", "69", "93"]

# Immersion facile
# ------------------------------------------------------------------------------
IMMERSION_FACILE_SITE_URL = os.getenv("IMMERSION_FACILE_SITE_URL", "https://staging.immersion-facile.beta.gouv.fr")

# Datadog
# ------------------------------------------------------------------------------
API_DATADOG_BASE_URL = "https://api.datadoghq.eu/api/v2"
API_DATADOG_API_KEY = os.getenv("API_DATADOG_API_KEY", None)
API_DATADOG_APPLICATION_KEY = os.getenv("API_DATADOG_APPLICATION_KEY", None)

# Sentry
API_SENTRY_BASE_URL = "https://sentry.io/api/0"
API_SENTRY_STATS_TOKEN = os.getenv("API_SENTRY_STATS_TOKEN")
API_SENTRY_ORG_NAME = os.getenv("API_SENTRY_ORG_NAME")
API_SENTRY_PROJECT_ID = os.getenv("API_SENTRY_PROJECT_ID")

# Updown
API_UPDOWN_TOKEN = os.getenv("API_UPDOWN_TOKEN")
API_UPDOWN_BASE_URL = "https://updown.io/api"
API_UPDOWN_CHECK_ID = os.getenv("API_UPDOWN_CHECK_ID")

# RDV-I/S
# ------------------------------------------------------------------------------
RDV_SOLIDARITES_API_BASE_URL = os.getenv("RDV_SOLIDARITES_API_BASE_URL")
RDV_SOLIDARITES_EMAIL = os.getenv("RDV_SOLIDARITES_EMAIL")
RDV_SOLIDARITES_PASSWORD = os.getenv("RDV_SOLIDARITES_PASSWORD")
RDV_SOLIDARITES_TOKEN_EXPIRY = os.getenv("RDV_SOLIDARITES_TOKEN_EXPIRY", 86000)  # Token expires after 24h (86400s)
RDV_INSERTION_API_BASE_URL = os.getenv("RDV_INSERTION_API_BASE_URL")
RDV_INSERTION_INVITE_HOLD_DURATION = datetime.timedelta(days=int(os.getenv("RDV_INSERTION_INVITE_HOLD_DAYS", 10)))
RDV_INSERTION_WEBHOOK_SECRET = os.getenv("RDV_INSERTION_WEBHOOK_SECRET")

# API Particuliers
# ------------------------------------------------------------------------------
API_PARTICULIER_BASE_URL = os.getenv("API_PARTICULIER_BASE_URL", "https://particulier.api.gouv.fr/api/")
API_PARTICULIER_TOKEN = os.getenv("API_PARTICULIER_TOKEN")

# Brevo
# ------------------------------------------------------------------------------
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_API_URL = "https://api.brevo.com/v3"

# Pilotage
# ------------------------------------------------------------------------------
PILOTAGE_SHOW_STATS_WEBINAR = os.getenv("PILOTAGE_SHOW_STATS_WEBINAR", True) in [True, "True", "true"]
PILOTAGE_SLACK_WEBHOOK_URL = os.getenv("PILOTAGE_SLACK_WEBHOOK_URL")

# Shared secrets
PILOTAGE_DATA_HASH_SALT = os.getenv("PILOTAGE_DATA_HASH_SALT")

# PostgreSQL database for communicating with the Pilotage.
PILOTAGE_DATASTORE_DB_HOST = os.getenv("PILOTAGE_DATASTORE_DB_HOST")
PILOTAGE_DATASTORE_DB_PORT = os.getenv("PILOTAGE_DATASTORE_DB_PORT")
PILOTAGE_DATASTORE_DB_DATABASE = os.getenv("PILOTAGE_DATASTORE_DB_DATABASE")
PILOTAGE_DATASTORE_DB_USER = os.getenv("PILOTAGE_DATASTORE_DB_USER")
PILOTAGE_DATASTORE_DB_PASSWORD = os.getenv("PILOTAGE_DATASTORE_DB_PASSWORD")

# S3 store for communicating with the Pilotage.
PILOTAGE_DATASTORE_S3_ENDPOINT_URL = os.getenv("PILOTAGE_DATASTORE_S3_ENDPOINT_URL")
PILOTAGE_DATASTORE_S3_ACCESS_KEY = os.getenv("PILOTAGE_DATASTORE_S3_ACCESS_KEY")
PILOTAGE_DATASTORE_S3_SECRET_KEY = os.getenv("PILOTAGE_DATASTORE_S3_SECRET_KEY")
PILOTAGE_DATASTORE_S3_BUCKET_NAME = os.getenv("PILOTAGE_DATASTORE_S3_BUCKET_NAME")

# Github
API_GITHUB_BASE_URL = "https://api.github.com"

# Territorial experimentation
# ------------------------------------------------------------------------------
JOB_APPLICATION_OPTIONAL_REFUSAL_REASON_DEPARTMENTS = ["69"]

SERIALIZATION_MODULES = {
    "json-no-auto-fields": "itou.utils.json_no_auto_fields_serializer",
}

# OTP
# ------------------------------------------------------------------------------
OTP_TOTP_ISSUER = f"Les Emplois de l'inclusion ({ITOU_ENVIRONMENT})"
OTP_ADMIN_HIDE_SENSITIVE_DATA = True
REQUIRE_OTP_FOR_STAFF = os.getenv("REQUIRE_OTP_FOR_STAFF", "True") == "True"

# anonymize users
# ------------------------------------------------------------------------------
SUSPEND_ANONYMIZE_JOBSEEKERS = os.getenv("SUSPEND_ANONYMIZE_JOBSEEKERS", "False") == "True"
SUSPEND_ANONYMIZE_PROFESSIONALS = os.getenv("SUSPEND_ANONYMIZE_PROFESSIONALS", "False") == "True"
SUSPEND_ANONYMIZE_CANCELLED_APPROVALS = os.getenv("SUSPEND_ANONYMIZE_CANCELLED_APPROVALS", "False") == "True"

# Mainenance mode
# ------------------------------------------------------------------------------
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "False") == "True"
MAINTENANCE_DESCRIPTION = os.getenv("MAINTENANCE_DESCRIPTION", None)

# Page size (lists)
# ------------------------------------------------------------------------------
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_SMALL = 10
PAGE_SIZE_LARGE = 50

# Nexus metabase db
# ------------------------------------------------------------------------------
NEXUS_METABASE_DB_HOST = os.getenv("NEXUS_METABASE_DB_HOST")
NEXUS_METABASE_DB_PORT = os.getenv("NEXUS_METABASE_DB_PORT")
NEXUS_METABASE_DB_DATABASE = os.getenv("NEXUS_METABASE_DB_DATABASE")
NEXUS_METABASE_DB_USER = os.getenv("NEXUS_METABASE_DB_USER")
NEXUS_METABASE_DB_PASSWORD = os.getenv("NEXUS_METABASE_DB_PASSWORD")
NEXUS_ALLOWED_REDIRECT_HOSTS = os.getenv("NEXUS_ALLOWED_REDIRECT_HOSTS", "").split(",")

nexus_key = os.getenv("NEXUS_AUTO_LOGIN_KEY")
NEXUS_AUTO_LOGIN_KEY = json.loads(nexus_key) if nexus_key else None
