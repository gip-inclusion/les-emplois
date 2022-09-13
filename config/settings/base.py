"""
Base settings to build other settings files upon.
https://docs.djangoproject.com/en/dev/ref/settings
"""
import datetime
import json
import os

from django.utils import timezone


# Paths.
# ------------------------------------------------------------------------------

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))

APPS_DIR = os.path.abspath(os.path.join(ROOT_DIR, "itou"))

EXPORT_DIR = os.environ.get("SCRIPT_EXPORT_PATH", f"{ROOT_DIR}/exports")
IMPORT_DIR = os.environ.get("SCRIPT_IMPORT_PATH", f"{ROOT_DIR}/imports")

# General.
# ------------------------------------------------------------------------------

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = os.environ.get("DJANGO_DEBUG") == "True"

ALLOWED_HOSTS = []

SITE_ID = 1

# Apps.
# ------------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.gis",
    "django.contrib.postgres",
    "django.forms",  # Required to override default Django widgets. See FORM_RENDERER
]

THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "anymail",
    "bootstrap4",
    "django_select2",
    "huey.contrib.djhuey",
    "rest_framework",  # DRF (Django Rest Framework).
    "rest_framework.authtoken",  # Required for DRF TokenAuthentication.
    "drf_spectacular",
    "django_filters",
    "import_export",
]


LOCAL_APPS = [
    # Core apps, order is important.
    "itou.utils",
    "itou.cities",
    "itou.jobs",
    "itou.users",
    "itou.siaes",
    "itou.prescribers",
    "itou.institutions",
    "itou.job_applications",
    "itou.approvals",
    "itou.eligibility",
    "itou.openid_connect.france_connect",
    "itou.openid_connect.inclusion_connect",
    "itou.invitations",
    "itou.external_data",
    "itou.metabase",
    "itou.asp",
    "itou.employee_record",
    "itou.siae_evaluations",
    # www.
    "itou.www.apply",
    "itou.www.approvals_views",
    "itou.www.autocomplete",
    "itou.www.dashboard",
    "itou.www.eligibility_views",
    "itou.www.home",
    "itou.www.prescribers_views",
    "itou.www.search",
    "itou.www.siaes_views",
    "itou.www.signup",
    "itou.www.invitations_views",
    "itou.www.stats",
    "itou.www.welcoming_tour",
    "itou.www.employee_record_views",
    "itou.www.siae_evaluations_views",
    # API
    "itou.api",
    # Status
    "itou.status",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Middleware.
# ------------------------------------------------------------------------------

DJANGO_MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ITOU_MIDDLEWARE = [
    "itou.utils.new_dns.middleware.NewDnsRedirectMiddleware",
    "itou.utils.perms.middleware.ItouCurrentOrganizationMiddleware",
]

MIDDLEWARE = DJANGO_MIDDLEWARE + ITOU_MIDDLEWARE

# URLs.
# ------------------------------------------------------------------------------

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"

# Templates.
# ------------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(APPS_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                # Django.
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                # Itou.
                "itou.utils.perms.context_processors.get_current_organization_and_perms",
                "itou.utils.settings_context_processors.expose_settings",
            ]
        },
    }
]

# Forms.
# ------------------------------------------------------------------------------

# Override default Django forms widgets templates.
# Requires django.forms in INSTALLED_APPS
# https://timonweb.com/django/overriding-field-widgets-in-django-doesnt-work-template-not-found-the-solution/
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# Database.
# ------------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ATOMIC_REQUESTS": False,  # We handle transactions manually in the code.
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "NAME": os.environ.get("ITOU_POSTGRES_DATABASE_NAME", "itou"),
        "USER": os.environ.get("ITOU_POSTGRES_USER", "itou"),
        "PASSWORD": os.environ.get("ITOU_POSTGRES_PASSWORD", "mdp"),
    }
}

# https://docs.djangoproject.com/en/3.2/releases/3.2/#customizing-type-of-auto-created-primary-keys
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Password validation.
# ------------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "itou.utils.password_validation.CnilCompositionPasswordValidator"},
]

# Internationalization.
# ------------------------------------------------------------------------------

LANGUAGE_CODE = "fr-FR"

TIME_ZONE = "Europe/Paris"

USE_I18N = True

USE_TZ = True

DATE_INPUT_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d %m %Y"]

# Static files (CSS, JavaScript, Images).
# ------------------------------------------------------------------------------

# Path to the directory where collectstatic will collect static files for deployment.
STATIC_ROOT = os.path.join(APPS_DIR, "static_collected")

STATIC_URL = "/static/"

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
)

STATICFILES_DIRS = (os.path.join(APPS_DIR, "static"),)

# Security.
# ------------------------------------------------------------------------------

CSRF_COOKIE_HTTPONLY = True

CSRF_COOKIE_SECURE = True

SECURE_BROWSER_XSS_FILTER = True

SECURE_CONTENT_TYPE_NOSNIFF = True

# Load the site over HTTPS only.
# TODO: use a small value for testing, once confirmed that HSTS didn't break anything increase it.
# https://docs.djangoproject.com/en/dev/ref/middleware/#http-strict-transport-security
SECURE_HSTS_SECONDS = 30

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SECURE = True

SESSION_EXPIRE_AT_BROWSER_CLOSE = True

SESSION_SERIALIZER = "itou.utils.session.JSONSerializer"

X_FRAME_OPTIONS = "DENY"

# Logging.
# https://docs.djangoproject.com/en/dev/topics/logging
# ----------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "null": {"class": "logging.NullHandler"},
        "api_console": {
            "class": "logging.StreamHandler",
            "formatter": "api_simple",
        },
    },
    "formatters": {
        "api_simple": {
            "format": "{levelname} {asctime} {pathname} : {message}",
            "style": "{",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
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
            "handlers": ["console"],
            "level": os.getenv("ITOU_LOG_LEVEL", "INFO"),
        },
        # Logger for DRF API application
        # Will be "log-drained": may need to adjust format
        "api_drf": {
            "handlers": ["api_console"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
        },
        # Huey; async tasks
        "huey": {
            "handlers": ["console"],
            "level": os.getenv("HUEY_LOG_LEVEL", "WARNING"),
        },
    },
}

# Auth.
# https://django-allauth.readthedocs.io/en/latest/configuration.html
# ------------------------------------------------------------------------------

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = (
    # Needed to login by username in Django admin.
    "django.contrib.auth.backends.ModelBackend",
    # `allauth` specific authentication methods, such as login by e-mail.
    "allauth.account.auth_backends.AuthenticationBackend",
)

# User authentication callbacks such as redirections after login.
# Replaces LOGIN_REDIRECT_URL, which is static, by ACCOUNT_ADAPTER which is dynamic.
# https://django-allauth.readthedocs.io/en/latest/advanced.html#custom-redirects
ACCOUNT_ADAPTER = "itou.users.adapter.UserAdapter"

ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_ATTEMPTS_LIMIT = 5  # Protects only the allauth login view.
ACCOUNT_LOGIN_ATTEMPTS_TIMEOUT = 600  # Seconds.
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_USER_DISPLAY = "itou.users.models.get_allauth_account_user_display"

# django-bootstrap4.
# https://django-bootstrap4.readthedocs.io/en/latest/settings.html
# ------------------------------------------------------------------------------

BOOTSTRAP4 = {
    "required_css_class": "form-group-required",
    # Remove the default `.is-valid` class that Bootstrap will style in green
    # otherwise empty required fields will be marked as valid. This might be
    # a bug in django-bootstrap4, it should be investigated.
    "success_css_class": "",
}

# APIs.
# ------------------------------------------------------------------------------

# Base Adresse Nationale (BAN).
# https://adresse.data.gouv.fr/faq
API_BAN_BASE_URL = "https://api-adresse.data.gouv.fr"

# https://api.gouv.fr/api/api-geo.html#doc_tech
API_GEO_BASE_URL = "https://geo.api.gouv.fr"

# INSEE API
API_INSEE_BASE_URL = "https://api.insee.fr"
API_INSEE_CONSUMER_KEY = os.environ.get("API_INSEE_CONSUMER_KEY", "")
API_INSEE_CONSUMER_SECRET = os.environ.get("API_INSEE_CONSUMER_SECRET", "")

# API Entreprise.
# https://api.gouv.fr/documentation/sirene_v3
API_ENTREPRISE_BASE_URL = f"{API_INSEE_BASE_URL}/entreprises/sirene/V3"

# Pôle emploi's Emploi Store Dev aka ESD. There is a production AND a recette environment:
#  - Production: https://www.pole-emploi.io
#  - Recette: https://peio.pe-qvr.fr/
# Key and secrets are on pole-emploi.io (prod and recette) accounts, the values are not the
# same depending on the environment
# Please note that some of APIs have a dry run mode which is handled through (possibly undocumented) scopes
# Recette settings:
## API_ESD_AUTH_BASE_URL="https://entreprise.pe-qvr.fr"
## API_ESD_BASE_URL="https://api-r.es-qvr.fr/partenaire"
# Production settings:
## API_ESD_AUTH_BASE_URL="https://entreprise.pole-emploi.fr"
## API_ESD_BASE_URL="https://api.emploi-store.fr/partenaire"
API_ESD = {
    "AUTH_BASE_URL": os.environ.get("API_ESD_AUTH_BASE_URL"),
    "KEY": os.environ.get("API_ESD_KEY", ""),
    "SECRET": os.environ.get("API_ESD_SECRET", ""),
    "BASE_URL": os.environ.get("API_ESD_BASE_URL"),
}


# PE Connect aka PEAMU - technically one of ESD's APIs.
# PEAM stands for Pôle emploi Access Management.
# Technically there are two PEAM distinct systems:
# - PEAM "Entreprise", PEAM-E or PEAME for short.
# - PEAM "Utilisateur", PEAM-U or PEAMU for short.
# To avoid confusion between the two when contacting ESD support,
# we get the habit to always explicitely state that we are using PEAM*U*.
# PE Connect is enabled by default, but a feature flag allows to deactivate it.
# Disabled in the DEMO environment.
PEAMU_ENABLED = os.environ.get("PEAMU_ENABLED", "True") == "True"
PEAMU_AUTH_BASE_URL = "https://authentification-candidat.pole-emploi.fr"
SOCIALACCOUNT_PROVIDERS = {
    "peamu": {
        "APP": {"key": "peamu", "client_id": API_ESD["KEY"], "secret": API_ESD["SECRET"]},
    },
}
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_ADAPTER = "itou.allauth_adapters.peamu.adapter.PEAMUSocialAccountAdapter"

# France Connect
# https://partenaires.franceconnect.gouv.fr/
# France Connect is enabled by default, but a feature flag allows to deactivate it.
# Disabled in the DEMO environment.
FRANCE_CONNECT_ENABLED = os.environ.get("FRANCE_CONNECT_ENABLED", "True") == "True"
FRANCE_CONNECT_BASE_URL = "https://app.franceconnect.gouv.fr/api/v1"
FRANCE_CONNECT_CLIENT_ID = os.environ.get("FRANCE_CONNECT_CLIENT_ID")
FRANCE_CONNECT_CLIENT_SECRET = os.environ.get("FRANCE_CONNECT_CLIENT_SECRET")


# Inclusion Connect
INCLUSION_CONNECT_BASE_URL = os.environ.get("INCLUSION_CONNECT_BASE_URL")
INCLUSION_CONNECT_REALM = os.environ.get("INCLUSION_CONNECT_REALM")
INCLUSION_CONNECT_CLIENT_ID = os.environ.get("INCLUSION_CONNECT_CLIENT_ID")
INCLUSION_CONNECT_CLIENT_SECRET = os.environ.get("INCLUSION_CONNECT_CLIENT_SECRET")

# Typeform
# ------------------------------------------------------------------------------

TYPEFORM_SECRET = os.environ.get("TYPEFORM_SECRET")
TYPEFORM_URL = "https://itou.typeform.com"

# Itou.
# ------------------------------------------------------------------------------

# This trick
# https://github.com/pennersr/django-allauth/issues/749#issuecomment-70402595
# fixes the following issue
# https://github.com/pennersr/django-allauth/issues/749
# Without this trick, python manage.py makemigrations
# would want to create a migration in django-allauth dependency
# /usr/local/lib/python3.9/site-packages/allauth/socialaccount/migrations/0004_auto_20200415_1510.py
# - Alter field provider on socialaccount
# - Alter field provider on socialapp
#
# This setting redirects the migrations for socialaccount to our directory
MIGRATION_MODULES = {
    "socialaccount": "itou.allauth_adapters.migrations",
}

# Environment, sets the type of env of the app (DEMO, REVIEW_APP, STAGING, DEV…)
ITOU_ENVIRONMENT = "PROD"
ITOU_PROTOCOL = "https"
ITOU_FQDN = "emplois.inclusion.beta.gouv.fr"
ITOU_EMAIL_CONTACT = "assistance@inclusion.beta.gouv.fr"
ITOU_EMAIL_PROLONGATION = "prolongation@inclusion.beta.gouv.fr"
ITOU_ASSISTANCE_URL = "https://communaute.inclusion.beta.gouv.fr/aide/emplois"

DEFAULT_FROM_EMAIL = "noreply@inclusion.beta.gouv.fr"

# FIXME(vperron): Those following lines are *not* settings. They are code constants that have
# no reason to change or be modified through the environment. They should be moved in a constants.py
# file in an app or in the module that uses them if it's a single Python module.
# This gives the fake impression that we have many settings when we don't, and forces code
# to import the whole Django settings (a full Django setup) when it may not be necessary.
# The same could be said about any non-environment dependant variable here.
ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY = "current_prescriber_organization"
ITOU_SESSION_CURRENT_SIAE_KEY = "current_siae"
ITOU_SESSION_CURRENT_INSTITUTION_KEY = "current_institution"
ITOU_SESSION_PRESCRIBER_SIGNUP_KEY = "prescriber_signup"
ITOU_SESSION_FACILITATOR_SIGNUP_KEY = "facilitator_signup"
ITOU_SESSION_NIR_KEY = "job_seeker_nir"
ITOU_SESSION_EDIT_SIAE_KEY = "edit_siae_session_key"
ITOU_SESSION_JOB_DESCRIPTION_KEY = "edit_job_description_key"
ITOU_SESSION_CURRENT_PAGE_KEY = "current_page"

SHOW_TEST_ACCOUNTS_BANNER = False

# Le marché de l'inclusion
LEMARCHE_OPEN_REGIONS = ["Hauts-de-France", "Grand Est", "Île-de-France"]

POLE_EMPLOI_EMAIL_SUFFIX = "@pole-emploi.fr"

# Documentation link.
ITOU_DOC_URL = "https://doc.inclusion.beta.gouv.fr"

# Communauté link.
ITOU_COMMUNITY_URL = "https://communaute.inclusion.beta.gouv.fr"

# Approvals
# ------------------------------------------------------------------------------

# Approval numbering prefix can be different for non-production envs
ASP_ITOU_PREFIX = "99999"

# On November 30th, 2021, we delivered approvals for AI structures.
# See itou.users.management.commands.import_ai_employees
AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL = os.environ.get("AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL", "")
AI_EMPLOYEES_STOCK_IMPORT_DATE = datetime.datetime(2021, 11, 30, tzinfo=timezone.utc)

# Metabase
# ------------------------------------------------------------------------------

# Metabase should only ever be populated:
# - from production (by clever cloud cronjob)
# - from local dev (by experimented metabase developers)
ALLOW_POPULATING_METABASE = False

METABASE_HOST = os.environ.get("METABASE_HOST")
METABASE_PORT = os.environ.get("METABASE_PORT")
METABASE_DATABASE = os.environ.get("METABASE_DATABASE")
METABASE_USER = os.environ.get("METABASE_USER")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD")

METABASE_DRY_RUN_ROWS_PER_QUERYSET = 1000

# Useful to troobleshoot whether the script runs a deluge of SQL requests.
METABASE_SHOW_SQL_REQUESTS = False

# Set how many rows are inserted at a time in metabase database.
# A bigger number makes the script faster until a certain point,
# but it also increases RAM usage.
# -- Bench results for self.populate_approvals()
# by batch of 100 => 2m38s
# by batch of 1000 => 2m23s
# -- Bench results for self.populate_diagnostics()
# by batch of 1 => 2m51s
# by batch of 10 => 19s
# by batch of 100 => 5s
# by batch of 1000 => 5s
METABASE_INSERT_BATCH_SIZE = 100

# Embedding signed Metabase dashboard
METABASE_SITE_URL = "https://stats.inclusion.beta.gouv.fr"
METABASE_SECRET_KEY = os.environ.get("METABASE_SECRET_KEY", "")

# Metabase embedded dashboards
METABASE_DASHBOARD_IDS = {
    # Public stats.
    "stats_public": 119,
    # Employer stats.
    "stats_siae_etp": 128,
    "stats_siae_hiring": 185,
    # Prescriber stats.
    "stats_cd": 118,
    "stats_pe_delay_main": 168,
    "stats_pe_delay_raw": 180,
    "stats_pe_conversion_main": 169,
    "stats_pe_conversion_raw": 182,
    "stats_pe_state_main": 149,
    "stats_pe_state_raw": 183,
    "stats_pe_tension": 162,
    # Institution stats - DDETS - department level.
    "stats_ddets_iae": 117,
    "stats_ddets_diagnosis_control": 144,
    "stats_ddets_hiring": 160,
    # Institution stats - DREETS - region level.
    "stats_dreets_iae": 117,
    "stats_dreets_hiring": 160,
    # Institution stats - DGEFP - nation level.
    "stats_dgefp_iae": 117,
    "stats_dgefp_diagnosis_control": 144,
    "stats_dgefp_af": 142,
}
PILOTAGE_DASHBOARDS_WHITELIST = json.loads(os.environ.get("PILOTAGE_DASHBOARDS_WHITELIST", "[]"))

# Some experimental stats are progressively being deployed to more and more specific beta users.
STATS_SIAE_USER_PK_WHITELIST = json.loads(os.environ.get("STATS_SIAE_USER_PK_WHITELIST", "[]"))

PILOTAGE_SITE_URL = "https://pilotage.inclusion.beta.gouv.fr"
PILOTAGE_ASSISTANCE_URL = "https://communaute.inclusion.beta.gouv.fr/aide/pilotage"

# Slack notifications sent by Metabase cronjobs.
SLACK_CRON_WEBHOOK_URL = os.environ.get("SLACK_CRON_WEBHOOK_URL", None)

# Huey / async
# Workers are run in prod via `CC_WORKER_COMMAND = django-admin run_huey`.
# ------------------------------------------------------------------------------

# Redis server URL:
# Provided by the Redis addon (itou-redis)
# Redis database to use with async (must be different for each environement)
# 1 <= REDIS_DB <= 100 (number of dbs available on CleverCloud)
REDIS_DB = os.environ.get("REDIS_DB", 1)
# Complete URL (containing the instance password)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# NOTE(vperron): those parameters are defaulted to the production instance.
# This means that we would crash if a task was sent and no Redis was present (in local dev for instance)
# I'm leaving this as-is, since this means that in development if we sent a task to huey we have
# to mock that call or crash. This makes sense, since either we would test a non-real async queue
# (in memory for instance) or just send something to some state and forget about it.

# Huey instance
# If any performance issue, increasing the number of workers *can* be a good idea
# Parameter `immediate` means `synchronous` (async here)
HUEY = {
    "name": "ITOU",
    # Don't store task results (see our Redis Post-Morten in documentation for more information)
    "results": False,
    "url": REDIS_URL + f"/?db={REDIS_DB}",
    "consumer": {
        "workers": 2,
        "worker_type": "thread",
    },
    "immediate": False,
}

# Email.
# https://anymail.readthedocs.io/en/stable/esps/mailjet/
# ------------------------------------------------------------------------------

ANYMAIL = {
    "MAILJET_API_KEY": os.environ.get("API_MAILJET_KEY"),
    "MAILJET_SECRET_KEY": os.environ.get("API_MAILJET_SECRET"),
    "WEBHOOK_SECRET": os.environ.get("MAILJET_WEBHOOK_SECRET"),
}

MAILJET_API_URL = "https://api.mailjet.com/v3.1"

# Asynchronous email backend.
# ------------------------------------------------------------------------------

# EMAIL_BACKEND points to an async wrapper of a "real" email backend
# The real backend is hardcoded in the wrapper to avoid multiple and
# confusing parameters in Django settings.
# Switch to a "standard" Django backend to get the synchronous behaviour back.
EMAIL_BACKEND = "itou.utils.emails.AsyncEmailBackend"

# Number of retries & retry delay parameters for emails (for async process)
SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS = 5 * 60
SEND_EMAIL_RETRY_TOTAL_TIME_IN_SECONDS = 24 * 3600

# DRF (Django Rest Framework)
# ------------------------------------------------------------------------------
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
    # See DEV template for an additional rendeder for DRF browseable API
    # https://www.django-rest-framework.org/api-guide/renderers/#custom-renderers
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        # For DRF browseable API access
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Default permissions for API views: user must be authenticated
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Throttling:
    # See: https://www.django-rest-framework.org/api-guide/throttling/
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # Default values for throttling rates:
    # - overridden in custom throttling classes,
    # - arbitrary values, update should the need arise.
    "DEFAULT_THROTTLE_RATES": {
        "anon": "12/minute",
        "user": "12/minute",
    },
}

# DRF Spectacular
# ------------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "API - Les emplois de l'inclusion",
    "DESCRIPTION": "Documentation de l'API **emplois.inclusion.beta.gouv.fr**",
    "VERSION": "1.0.0",
}

# Requests
# ------------------------------------------------------------------------------
# Requests default timeout is None... See https://blog.mathieu-leplatre.info/handling-requests-timeout-in-python.html
# Use `httpx`, which has a default timeout of 5 seconds, when possible.
# Otherwise, set a timeout like this:
# requests.get(timeout=settings.REQUESTS_TIMEOUT)
REQUESTS_TIMEOUT = 5  # in seconds

# ASP SFTP connection
# ------------------------------------------------------------------------------
ASP_FS_SFTP_HOST = os.getenv("ASP_FS_SFTP_HOST", "localhost")
ASP_FS_SFTP_PORT = os.getenv("ASP_FS_SFTP_PORT", 22)
ASP_FS_SFTP_USER = os.getenv("ASP_FS_SFTP_USER")
# Path to SSH keypair for SFTP connection
ASP_FS_SFTP_PRIVATE_KEY_PATH = os.getenv("ASP_FS_SFTP_PRIVATE_KEY_PATH")
ASP_FS_KNOWN_HOSTS = os.getenv("ASP_FS_KNOWN_HOSTS")
# SFTP path: Where to put new employee records for ASP validation
ASP_FS_REMOTE_UPLOAD_DIR = "depot"
# SFTP path: Where to get submitted employee records validation feedback
ASP_FS_REMOTE_DOWNLOAD_DIR = "retrait"

# S3 uploads
# ------------------------------------------------------------------------------
S3_STORAGE_ACCESS_KEY_ID = os.environ.get("CELLAR_ADDON_KEY_ID", "")
S3_STORAGE_SECRET_ACCESS_KEY = os.environ.get("CELLAR_ADDON_KEY_SECRET", "")
S3_STORAGE_ENDPOINT_DOMAIN = os.environ.get("CELLAR_ADDON_HOST", "")
S3_STORAGE_BUCKET_NAME = os.environ.get("S3_STORAGE_BUCKET_NAME", "")
S3_STORAGE_BUCKET_REGION = os.environ.get("S3_STORAGE_BUCKET_REGION", "")

STORAGE_UPLOAD_KINDS = {
    "default": {
        "allowed_mime_types": ["application/pdf"],
        "upload_expiration": 90 * 60,  # in seconds
        "key_path": "",  # appended before the file key. No backslash!
        "max_files": 1,
        "max_file_size": 5,  # in mb
        "timeout": 20000,  # in ms
    },
    "resume": {
        "key_path": "resume",
    },
    "evaluations": {
        "key_path": "evaluations",
    },
}

# Employee records
# ------------------------------------------------------------------------------
# Employee record data archiving / pruning:
# "Proof of record" model field is erased after this delay (in days)
EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS = int(os.environ.get("EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS", 13 * 30))

# This is the official and final production phase date of the employee record feature.
# It is used as parameter to filter the eligible job applications for the feature.
# (no job application before this date can be used for this feature)
EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE = timezone.datetime(2021, 9, 27, tzinfo=timezone.utc)

# Only PROD or temporary tests environments are able to transfer employee records data to ASP
# This is disabled by default, overidden in prod settings, and can be set
# via local dev settings or env vars for a temporary environment.
EMPLOYEE_RECORD_TRANSFER_ENABLED = bool(os.environ.get("EMPLOYEE_RECORD_TRANSFER_ENABLED", False))
