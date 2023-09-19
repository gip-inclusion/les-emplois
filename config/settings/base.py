"""
Base settings to build other settings files upon.
https://docs.djangoproject.com/en/dev/ref/settings
"""
import json
import os

from dotenv import load_dotenv

from ..sentry import sentry_init


load_dotenv()

# Django settings
# ---------------

_current_dir = os.path.dirname(os.path.realpath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(_current_dir, "../.."))

APPS_DIR = os.path.abspath(os.path.join(ROOT_DIR, "itou"))

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")

DEBUG = os.getenv("DJANGO_DEBUG", "False") == "True"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "inclusion.beta.gouv.fr,emplois.inclusion.beta.gouv.fr").split(",")

SITE_ID = 1

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
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "django_filters",
    "django_htmx",
    "import_export",
    "hijack",
    "hijack.contrib.admin",
    "pgtrigger",
]


LOCAL_APPS = [
    "itou.utils",
    "itou.cities",
    "itou.jobs",
    "itou.users",
    "itou.siaes",
    "itou.prescribers",
    "itou.institutions",
    "itou.files",
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
    "itou.geo",
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
    "itou.api",
    "itou.status",
    "itou.antivirus",
    "itou.scripts",
    "itou.settings_viewer",
    "itou.analytics",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


DJANGO_MIDDLEWARES = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

THIRD_PARTY_MIDDLEWARES = [
    "csp.middleware.CSPMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "hijack.middleware.HijackUserMiddleware",
]

ITOU_MIDDLEWARES = [
    "itou.utils.new_dns.middleware.NewDnsRedirectMiddleware",
    "itou.utils.perms.middleware.ItouCurrentOrganizationMiddleware",
    "itou.www.middleware.never_cache",
]

MIDDLEWARE = DJANGO_MIDDLEWARES + THIRD_PARTY_MIDDLEWARES + ITOU_MIDDLEWARES

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
                "itou.utils.context_processors.expose_enums",
                "itou.utils.context_processors.matomo",
            ]
        },
    }
]

# Override default Django forms widgets templates.
# Requires django.forms in INSTALLED_APPS
# https://timonweb.com/django/overriding-field-widgets-in-django-doesnt-work-template-not-found-the-solution/
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# Note how we use Clever Cloud environment variables here. No way for now to alias them :/
DATABASES = {
    "default": {
        "ATOMIC_REQUESTS": True,
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.getenv("POSTGRESQL_ADDON_DB"),
        # FIXME(vperron): We should get rid of those Clever Cloud proprietary values in our code
        # and alias them as soon as we can in our pre-build and pre-run scripts. But those scripts
        # will be defined in a later PR.
        "HOST": os.getenv("POSTGRESQL_ADDON_DIRECT_HOST") or os.getenv("POSTGRESQL_ADDON_HOST"),
        "PORT": os.getenv("POSTGRESQL_ADDON_DIRECT_PORT") or os.getenv("POSTGRESQL_ADDON_PORT"),
        "USER": os.getenv("POSTGRESQL_ADDON_CUSTOM_USER") or os.getenv("POSTGRESQL_ADDON_USER"),
        "PASSWORD": os.getenv("POSTGRESQL_ADDON_CUSTOM_PASSWORD") or os.getenv("POSTGRESQL_ADDON_PASSWORD"),
        "OPTIONS": {
            "connect_timeout": 5,
        },
    }
}

SQL_DEBUG = bool(os.getenv("SQL_DEBUG"))

if os.getenv("DATABASE_PERSISTENT_CONNECTIONS") == "True":
    # Since we have the health checks enabled, no need to define a max age:
    # if the connection was closed on the database side, the check will detect it
    DATABASES["default"]["CONN_MAX_AGE"] = None
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
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
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

STATICFILES_FINDERS = (
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

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
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

BOOTSTRAP4 = {
    "required_css_class": "form-group-required",
    # Remove the default `.is-valid` class that Bootstrap will style in green
    # otherwise empty required fields will be marked as valid. This might be
    # a bug in django-bootstrap4, it should be investigated.
    "success_css_class": "",
}


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


# ITOU settings
# -------------


# Environment, sets the type of env of the app (PROD, FAST-MACHINE, DEMO, DEV…)
ITOU_ENVIRONMENT = os.getenv("ITOU_ENVIRONMENT", "PROD")
ITOU_PROTOCOL = "https"
ITOU_FQDN = os.getenv("ITOU_FQDN", "emplois.inclusion.beta.gouv.fr")
ITOU_EMAIL_CONTACT = os.getenv("ITOU_EMAIL_CONTACT", "assistance@inclusion.beta.gouv.fr")
API_EMAIL_CONTACT = os.getenv("API_EMAIL_CONTACT", "api@inclusion.beta.gouv.fr")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@inclusion.beta.gouv.fr")

# Sentry
# Expose the value through the settings_viewer app.
SENTRY_DSN = os.getenv("SENTRY_DSN")
sentry_init()

SHOW_DEMO_ACCOUNTS_BANNER = ITOU_ENVIRONMENT in ("DEMO", "REVIEW-APP")

# https://adresse.data.gouv.fr/faq
API_BAN_BASE_URL = os.getenv("API_BAN_BASE_URL")

# https://api.gouv.fr/api/api-geo.html#doc_tech
API_GEO_BASE_URL = os.getenv("API_GEO_BASE_URL")

# https://api.insee.fr/catalogue/site/pages/list-apis.jag
API_INSEE_BASE_URL = os.getenv("API_INSEE_BASE_URL")
API_INSEE_CONSUMER_KEY = os.getenv("API_INSEE_CONSUMER_KEY")
API_INSEE_CONSUMER_SECRET = os.getenv("API_INSEE_CONSUMER_SECRET")
# https://api.insee.fr/catalogue/site/themes/wso2/subthemes/insee/pages/item-info.jag?name=Sirene&version=V3&provider=insee
API_INSEE_SIRENE_BASE_URL = f"{API_INSEE_BASE_URL}/entreprises/sirene/V3"

# Pôle emploi's Emploi Store Dev aka ESD. There is a production AND a recette environment.
# Key and secrets are stored on pole-emploi.io (prod and recette) accounts, the values are not the
# same depending on the environment
# Please note that some of APIs have a dry run mode which is handled through (possibly undocumented) scopes
API_ESD = {
    "AUTH_BASE_URL": os.getenv("API_ESD_AUTH_BASE_URL"),
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
SOCIALACCOUNT_PROVIDERS = {
    "peamu": {
        "APP": {"key": "peamu", "client_id": API_ESD["KEY"], "secret": API_ESD["SECRET"]},
    },
}
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_ADAPTER = "itou.allauth_adapters.peamu.adapter.PEAMUSocialAccountAdapter"

# France Connect https://partenaires.franceconnect.gouv.fr/
FRANCE_CONNECT_BASE_URL = os.getenv("FRANCE_CONNECT_BASE_URL")
FRANCE_CONNECT_CLIENT_ID = os.getenv("FRANCE_CONNECT_CLIENT_ID")
FRANCE_CONNECT_CLIENT_SECRET = os.getenv("FRANCE_CONNECT_CLIENT_SECRET")

INCLUSION_CONNECT_BASE_URL = os.getenv("INCLUSION_CONNECT_BASE_URL")
INCLUSION_CONNECT_CLIENT_ID = os.getenv("INCLUSION_CONNECT_CLIENT_ID")
INCLUSION_CONNECT_CLIENT_SECRET = os.getenv("INCLUSION_CONNECT_CLIENT_SECRET")

TALLY_URL = os.getenv("TALLY_URL")

METABASE_HOST = os.getenv("METABASE_HOST")
METABASE_PORT = os.getenv("METABASE_PORT")
METABASE_DATABASE = os.getenv("METABASE_DATABASE")
METABASE_USER = os.getenv("METABASE_USER")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD")

# Embedding signed Metabase dashboard
METABASE_SITE_URL = os.getenv("METABASE_SITE_URL")
METABASE_SECRET_KEY = os.getenv("METABASE_SECRET_KEY")

METABASE_HASH_SALT = os.getenv("METABASE_HASH_SALT")

ASP_ITOU_PREFIX = "99999"

PILOTAGE_DASHBOARDS_WHITELIST = json.loads(
    os.getenv(
        "PILOTAGE_DASHBOARDS_WHITELIST", "[63, 90, 32, 52, 54, 116, 43, 136, 140, 129, 150, 217, 218, 216, 300, 336]"
    )
)

# Only ACIs given by Convergence France may access some contracts
ACI_CONVERGENCE_SIRET_WHITELIST = json.loads(os.getenv("ACI_CONVERGENCE_SIRET_WHITELIST", "[]"))

# Specific experimental stats are progressively being deployed to more and more users and/or siaes.
# Kept as a setting to not let User/Siae PKs in clear in the code.
STATS_SIAE_ASP_ID_WHITELIST = json.loads(os.getenv("STATS_SIAE_ASP_ID_WHITELIST", "[]"))
STATS_SIAE_USER_PK_WHITELIST = json.loads(os.getenv("STATS_SIAE_USER_PK_WHITELIST", "[]"))
STATS_CD_DEPARTMENT_WHITELIST = ["13", "37", "38", "41", "45", "49"]

# Slack notifications sent by Metabase cronjobs.
SLACK_CRON_WEBHOOK_URL = os.getenv("SLACK_CRON_WEBHOOK_URL")

# Production instances (`PROD`, `DEMO`, `FAST-MACHINE`, ...) share the same redis but different DB
REDIS_URL = os.getenv("REDIS_URL")
REDIS_DB = os.getenv("REDIS_DB")

HUEY = {
    "name": "ITOU",
    # Don't store task results (see our Redis Post-Morten in documentation for more information)
    "results": False,
    "url": f"{REDIS_URL}/?db={REDIS_DB}",
    "consumer": {
        "workers": 2,
        "worker_type": "thread",
    },
    "immediate": ITOU_ENVIRONMENT not in ("DEMO", "PROD"),
}

MAILJET_API_KEY_PRINCIPAL = os.getenv("API_MAILJET_KEY_PRINCIPAL")
MAILJET_SECRET_KEY_PRINCIPAL = os.getenv("API_MAILJET_SECRET_PRINCIPAL")

# Email https://anymail.readthedocs.io/en/stable/esps/mailjet/
ANYMAIL = {
    # it's the default but our probes need this at import time.
    "MAILJET_API_URL": "https://api.mailjet.com/v3.1/",
    "MAILJET_API_KEY": os.getenv("API_MAILJET_KEY_APP"),
    "MAILJET_SECRET_KEY": os.getenv("API_MAILJET_SECRET_APP"),
    "WEBHOOK_SECRET": os.getenv("MAILJET_WEBHOOK_SECRET"),
}

EMAIL_BACKEND = "itou.utils.tasks.AsyncEmailBackend"
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

SPECTACULAR_SETTINGS = {
    "TITLE": "API - Les emplois de l'inclusion",
    "DESCRIPTION": "Documentation de l'API **emplois.inclusion.beta.gouv.fr**",
    "VERSION": "1.0.0",
    "ENUM_NAME_OVERRIDES": {
        "SiaeKindEnum": "itou.siaes.enums.SiaeKind",
        "PrescriberOrganizationKindEnum": "itou.prescribers.enums.PrescriberOrganizationKind",
    },
    # Allows to document the choices of a field even if the serializer has allow_null=True.
    # cf. https://github.com/tfranzel/drf-spectacular/issues/235
    "ENUM_ADD_EXPLICIT_BLANK_NULL_CHOICE": False,
}

# Requests default timeout is None... See https://blog.mathieu-leplatre.info/handling-requests-timeout-in-python.html
# Use `httpx`, which has a default timeout of 5 seconds, when possible.
# Otherwise, set a timeout like this:
# requests.get(timeout=settings.REQUESTS_TIMEOUT)
REQUESTS_TIMEOUT = 5  # in seconds

# ASP SFTP connection
# ------------------------------------------------------------------------------
ASP_FS_SFTP_HOST = os.getenv("ASP_FS_SFTP_HOST")
ASP_FS_SFTP_PORT = int(os.getenv("ASP_FS_SFTP_PORT", "22"))
ASP_FS_SFTP_USER = os.getenv("ASP_FS_SFTP_USER")
# Path to SSH keypair for SFTP connection
ASP_FS_SFTP_PRIVATE_KEY_PATH = os.getenv("ASP_FS_SFTP_PRIVATE_KEY_PATH")
ASP_FS_KNOWN_HOSTS = os.getenv("ASP_FS_KNOWN_HOSTS")

# S3 uploads
# ------------------------------------------------------------------------------
S3_STORAGE_ACCESS_KEY_ID = os.getenv("CELLAR_ADDON_KEY_ID")
S3_STORAGE_SECRET_ACCESS_KEY = os.getenv("CELLAR_ADDON_KEY_SECRET")
S3_STORAGE_ENDPOINT_DOMAIN = os.getenv("CELLAR_ADDON_HOST")
S3_STORAGE_BUCKET_NAME = os.getenv("S3_STORAGE_BUCKET_NAME")
S3_STORAGE_BUCKET_REGION = "eu-west-3"

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
    "prolongation_report": {
        "allowed_mime_types": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        "max_file_size": 1,
        "key_path": "prolongation_report",
    },
}

HIJACK_PERMISSION_CHECK = "itou.utils.perms.user.has_hijack_perm"
HIJACK_ALLOWED_USER_EMAILS = [s.lower() for s in os.getenv("HIJACK_ALLOWED_USER_EMAILS", "").split(",") if s]

EXPORT_DIR = os.getenv("SCRIPT_EXPORT_PATH", f"{ROOT_DIR}/exports")
IMPORT_DIR = os.getenv("SCRIPT_IMPORT_PATH", f"{ROOT_DIR}/imports")

MATOMO_BASE_URL = os.getenv("MATOMO_BASE_URL")
MATOMO_AUTH_TOKEN = os.getenv("MATOMO_AUTH_TOKEN")

# Content Security Policy
# Beware, some browser extensions may prevent the reports to be sent to sentry with CORS errors.
CSP_BASE_URI = ["'none'"]  # We don't use any <base> element in our code, so let's forbid it
CSP_DEFAULT_SRC = ["'self'"]
CSP_FRAME_SRC = [
    "https://app.livestorm.co",  # Upcoming events from the homepage
    "*.hotjar.com",
    # For stats/pilotage views
    "https://tally.so",
    "https://stats.inclusion.beta.gouv.fr",
    "https://pilotage.inclusion.beta.gouv.fr",
    "https://communaute.inclusion.beta.gouv.fr",
    "https://inclusion.beta.gouv.fr",
    "blob:",  # For downloading Metabase questions as CSV/XSLX/JSON on Firefox etc
    "data:",  # For downloading Metabase questions as PNG on Firefox etc
]
CSP_FRAME_ANCESTORS = [
    "https://pilotage.inclusion.beta.gouv.fr",
]
CSP_IMG_SRC = [
    "'self'",
    "data:",  # Because of tarteaucitron.js
    # OpenStreetMap tiles for django admin maps: both tile. and *.tile are used
    "https://tile.openstreetmap.org",
    "https://*.tile.openstreetmap.org",
    "*.hotjar.com",
    "https://cdn.redoc.ly",
]
CSP_STYLE_SRC = [
    "'self'",
    # It would be better to whilelist styles hashes but it's to much work for now.
    "'unsafe-inline'",
    "https://fonts.googleapis.com/",  # Used in theme-inclusion
]
CSP_FONT_SRC = [
    "'self'",
    # '*' does not allows 'data:' fonts
    "data:",  # Because of tarteaucitron.js
]
CSP_SCRIPT_SRC = [
    "'self'",
    "https://stats.inclusion.beta.gouv.fr",
    "*.hotjar.com",
    "https://tally.so",
]
# Some browsers don't seem to fallback on script-src if script-src-elem is not there
# But some other don't support script-src-elem... just copy one into the other
CSP_SCRIPT_SRC_ELEM = CSP_SCRIPT_SRC
CSP_CONNECT_SRC = [
    "'self'",
    "*.sentry.io",  # Allow to send reports to sentry without CORS errors.
    "*.hotjar.com",
    "*.hotjar.io",
    "wss://*.hotjar.com",
]
CSP_OBJECT_SRC = ["'none'"]

if MATOMO_BASE_URL:
    CSP_IMG_SRC.append(MATOMO_BASE_URL)
    CSP_SCRIPT_SRC.append(MATOMO_BASE_URL)
    CSP_CONNECT_SRC.append(MATOMO_BASE_URL)

CSP_WORKER_SRC = [
    "'self' blob:",  # Redoc seems to use blob:https://emplois.inclusion.beta.gouv.fr/some-ran-dom-uu-id
]
if S3_STORAGE_ENDPOINT_DOMAIN:
    CSP_CONNECT_SRC += [
        f"https://{S3_STORAGE_ENDPOINT_DOMAIN}",
    ]
CSP_INCLUDE_NONCE_IN = ["script-src", "script-src-elem"]
CSP_REPORT_URI = os.getenv("CSP_REPORT_URI", None)

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL")

FORCE_IC_LOGIN = True
