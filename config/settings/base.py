"""
Base settings to build other settings files upon.
https://docs.djangoproject.com/en/dev/ref/settings
"""
import os


# Paths.
# ------------------------------------------------------------------------------

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))

APPS_DIR = os.path.abspath(os.path.join(ROOT_DIR, "itou"))

EXPORT_DIR = f"{ROOT_DIR}/exports"

IMPORT_DIR = f"{ROOT_DIR}/imports"

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
    "bootstrap_datepicker_plus",
    "django_select2",
    "huey.contrib.djhuey",
    "rest_framework",  # DRF (Django Rest Framework).
    "rest_framework.authtoken",  # Required for DRF TokenAuthentication.
]


LOCAL_APPS = [
    # Core apps, order is important.
    "itou.utils",
    "itou.cities",
    "itou.jobs",
    "itou.users",
    "itou.siaes",
    "itou.prescribers",
    "itou.job_applications",
    "itou.approvals",
    "itou.eligibility",
    "itou.invitations",
    "itou.external_data",
    "itou.metabase",
    "itou.asp",
    "itou.employee_record",
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
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "itou.utils.password_validation.CnilCompositionPasswordValidator"},
]

# Internationalization.
# ------------------------------------------------------------------------------

LANGUAGE_CODE = "fr-FR"

TIME_ZONE = "Europe/Paris"

USE_I18N = True

USE_L10N = True

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

SESSION_EXPIRE_AT_BROWSER_CLOSE = True

SESSION_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True

CSRF_COOKIE_HTTPONLY = True

CSRF_COOKIE_SECURE = True

SECURE_BROWSER_XSS_FILTER = True

X_FRAME_OPTIONS = "DENY"

SECURE_CONTENT_TYPE_NOSNIFF = True

# Logging.
# https://docs.djangoproject.com/en/dev/topics/logging
# ----------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "null": {"class": "logging.NullHandler"},
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
            "level": os.getenv("DJANGO_LOG_LEVEL", "DEBUG"),
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
ACCOUNT_LOGIN_ATTEMPTS_TIMEOUT = 300  # Seconds.
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

# API Entreprise.
# https://dashboard.entreprise.api.gouv.fr/login (login is done through auth.api.gouv.fr)
# https://doc.entreprise.api.gouv.fr/
API_ENTREPRISE_BASE_URL = "https://entreprise.api.gouv.fr/v2"
API_ENTREPRISE_CONTEXT = "emplois.inclusion.beta.gouv.fr"
API_ENTREPRISE_RECIPIENT = os.environ.get("API_ENTREPRISE_RECIPIENT")
API_ENTREPRISE_TOKEN = os.environ.get("API_ENTREPRISE_TOKEN")

# Pôle emploi's Emploi Store Dev aka ESD.
# https://www.emploi-store-dev.fr/portail-developpeur/catalogueapi
API_ESD_KEY = os.environ.get("API_ESD_KEY", "")
API_ESD_SECRET = os.environ.get("API_ESD_SECRET", "")
API_ESD_AUTH_BASE_URL = "https://entreprise.pole-emploi.fr"
API_ESD_BASE_URL = "https://api.emploi-store.fr/partenaire"

# PE Connect aka PEAMU - technically one of ESD's APIs.
# PEAM stands for Pôle emploi Access Management.
# Technically there are two PEAM distinct systems:
# - PEAM "Entreprise", PEAM-E or PEAME for short.
# - PEAM "Utilisateur", PEAM-U or PEAMU for short.
# To avoid confusion between the two when contacting ESD support,
# we get the habit to always explicitely state that we are using PEAM*U*.
PEAMU_AUTH_BASE_URL = "https://authentification-candidat.pole-emploi.fr"
SOCIALACCOUNT_PROVIDERS = {
    "peamu": {
        "APP": {"key": "peamu", "client_id": API_ESD_KEY, "secret": API_ESD_SECRET},
    },
}
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_ADAPTER = "itou.allauth_adapters.peamu.adapter.PEAMUSocialAccountAdapter"

# PDFShift
# ------------------------------------------------------------------------------

PDFSHIFT_API_KEY = os.environ.get("PDFSHIFT_API_KEY")
PDFSHIFT_SANDBOX_MODE = os.environ.get("DJANGO_DEBUG")

# Typeform
# ------------------------------------------------------------------------------

TYPEFORM_SECRET = os.environ.get("TYPEFORM_SECRET")

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
ITOU_EMAIL_CONTACT = "contact@inclusion.beta.gouv.fr"
ITOU_ASSISTANCE_URL = "https://assistance.inclusion.beta.gouv.fr"

DEFAULT_FROM_EMAIL = "noreply@inclusion.beta.gouv.fr"

ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY = "current_prescriber_organization"
ITOU_SESSION_CURRENT_SIAE_KEY = "current_siae"
ITOU_SESSION_JOB_APPLICATION_KEY = "job_application"
ITOU_SESSION_PRESCRIBER_SIGNUP_KEY = "prescriber_signup"

# Typeform survey links to include in some emails
ITOU_EMAIL_APPROVAL_SURVEY_URL = "https://itou.typeform.com/to/S7QwC0yy"
ITOU_EMAIL_PRESCRIBER_NEW_HIRING_URL = "https://startupsbeta.typeform.com/to/X40eJC"

# Some external libraries, as PDF Shift, need access to static files
# but they can't access them when working locally.
# Use the staging domain name when this case arises.
ITOU_STAGING_DN = "staging.emplois.inclusion.beta.gouv.fr"

SHOW_TEST_ACCOUNTS_BANNER = False

# Le marché de l'inclusion
LEMARCHE_OPEN_REGIONS = ["Hauts-de-France", "Grand Est", "Île-de-France"]

POLE_EMPLOI_EMAIL_SUFFIX = "@pole-emploi.fr"

# Documentation links
ITOU_DOC_URL = "https://doc.inclusion.beta.gouv.fr"
ITOU_DOC_PASS_VERIFICATION_URL = f"{ITOU_DOC_URL}/pourquoi-une-plateforme-de-linclusion/pass-iae-agrement-plus-simple-cest-a-dire#verification-des-demandes-de-pass-iae"

# Communauté links.
ITOU_COMMUNITY_URL = "https://communaute.inclusion.beta.gouv.fr"

# Approvals
# ------------------------------------------------------------------------------

# Approval numbering prefix can be different for non-production envs
ASP_ITOU_PREFIX = "99999"

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

# Metabase embedded dashboard IDs
PUBLIC_STATS_DASHBOARD_ID = 34
ADVANCED_STATS_DASHBOARD_ID = 43
DIRECCTE_STATS_DASHBOARD_ID = 36

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

# Huey instance
# If any performance issue, increasing the number of workers *can* be a good idea
# Parameter `immediate` means `synchronous` (async here)
HUEY = {
    "name": "ITOU",
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
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Renderer
    # https://www.django-rest-framework.org/api-guide/renderers/#custom-renderers
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
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
ASP_FS_SFTP_USER = os.getenv("API_FS_SFTP_USER")
ASP_FS_SFTP_PRIVATE_KEY_PATH = os.getenv("ASP_FS_SFTP_PRIVATE_KEY_PATH")
ASP_FS_KNOWN_HOSTS = os.getenv("ASP_FS_KNOWN_HOSTS")
# SFTP path: Where to put new employee records for ASP validation
ASP_FS_REMOTE_UPLOAD_DIR = "depot"
# SFTP path: Where to get submitted employee records validation feedback
ASP_FS_REMOTE_DOWNLOAD_DIR = "retrait"
