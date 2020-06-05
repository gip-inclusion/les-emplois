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

# General.
# ------------------------------------------------------------------------------

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = os.environ["DJANGO_DEBUG"] == "True"

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
]

THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "anymail",
    "bootstrap4",
    "bootstrap_datepicker_plus",
    "django_select2",
    "mathfilters",
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
    "itou.metabase",
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

ITOU_MIDDLEWARE = ["itou.utils.perms.middleware.ItouCurrentOrganizationMiddleware"]

MIDDLEWARE = DJANGO_MIDDLEWARE + ITOU_MIDDLEWARE

# URLs.
# ------------------------------------------------------------------------------

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"

# Session.
# ------------------------------------------------------------------------------

SESSION_SAVE_EVERY_REQUEST = True

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

# Database.
# ------------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "NAME": os.environ.get("ITOU_POSTGRES_DATABASE_NAME", "itou"),
        "USER": os.environ.get("ITOU_POSTGRES_USER", "itou"),
        "PASSWORD": os.environ.get("ITOU_POSTGRES_PASSWORD", "mdp"),
    }
}

METABASE_HOST = os.environ.get("METABASE_HOST")
METABASE_PORT = os.environ.get("METABASE_PORT")
METABASE_DATABASE = os.environ.get("METABASE_DATABASE")
METABASE_USER = os.environ.get("METABASE_USER")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD")

ATOMIC_REQUESTS = True

# Password validation.
# ------------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
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

# Email.
# https://anymail.readthedocs.io/en/stable/esps/mailjet/
# ------------------------------------------------------------------------------

EMAIL_BACKEND = "anymail.backends.mailjet.EmailBackend"

ANYMAIL = {
    "MAILJET_API_KEY": os.environ["API_MAILJET_KEY"],
    "MAILJET_SECRET_KEY": os.environ["API_MAILJET_SECRET"],
}

MAILJET_API_URL = "https://api.mailjet.com/v3"

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

LOGIN_REDIRECT_URL = "dashboard:index"

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

# Sirene - V3
# https://api.insee.fr/catalogue/
# https://github.com/sne3ks/api_insee
# > Autorise 30 requêtes par minute pour chaque application des utilisateurs.
# > Quota par défaut pour tout nouveau compte.
API_INSEE_KEY = os.environ["API_INSEE_KEY"]
API_INSEE_SECRET = os.environ["API_INSEE_SECRET"]

# Pôle emploi's Emploi Store Dev aka ESD.
# https://www.emploi-store-dev.fr/portail-developpeur/catalogueapi
API_ESD_KEY = os.environ["API_ESD_KEY"]
API_ESD_SECRET = os.environ["API_ESD_SECRET"]
API_ESD_AUTH_BASE_URL = "https://entreprise.pole-emploi.fr"
API_ESD_BASE_URL = "https://api.emploi-store.fr/partenaire"

# PE Connect aka PEAMU - technically one of ESD's APIs.
# PEAM stands for Pôle Emploi Access Management.
# Technically there are two PEAM distinct systems:
# - PEAM "Entreprise", PEAM-E or PEAME for short.
# - PEAM "Utilisateur", PEAM-U or PEAMU for short.
# To avoid confusion between the two when contacting ESD support,
# we get the habit to always explicitely state that we are using PEAM*U*.
PEAMU_AUTH_BASE_URL = 'https://authentification-candidat.pole-emploi.fr'
SOCIALACCOUNT_PROVIDERS={
    "peamu": {
        "APP": {
            "key": "peamu",
            "client_id": API_ESD_KEY,
            "secret": API_ESD_SECRET
        },
    },
}
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_ADAPTER = "itou.allauth.peamu.adapter.PEAMUSocialAccountAdapter"

# PDFShift
PDFSHIFT_API_KEY = os.environ["PDFSHIFT_API_KEY"]
PDFSHIFT_SANDBOX_MODE = os.environ.get("DJANGO_DEBUG")

# Itou.
# ------------------------------------------------------------------------------

# Environment, sets the type of env of the app (DEMO, REVIEW_APP, STAGING, DEV…)
ITOU_ENVIRONMENT = "PROD"
ITOU_PROTOCOL = "https"
ITOU_FQDN = "inclusion.beta.gouv.fr"
ITOU_EMAIL_CONTACT = "contact@inclusion.beta.gouv.fr"
DEFAULT_FROM_EMAIL = "noreply@inclusion.beta.gouv.fr"

ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY = "current_prescriber_organization"
ITOU_SESSION_CURRENT_SIAE_KEY = "current_siae"
ITOU_SESSION_JOB_APPLICATION_KEY = "job_application"

# Typeform survey links to include in some emails
ITOU_EMAIL_APPROVAL_SURVEY_LINK = "https://startupsbeta.typeform.com/to/au9d8P"
ITOU_EMAIL_PRESCRIBER_NEW_HIRING_LINK = "https://startupsbeta.typeform.com/to/X40eJC"

# Some external libraries, as PDF Shift, need access to static files
# but they can't access them when working locally.
# Use the staging domain name when this case arises.
ITOU_STAGING_DN = "staging.inclusion.beta.gouv.fr"

SHOW_TEST_ACCOUNTS_BANNER = False

# Approvals
# ------------------------------------------------------------------------------
# Approval numbering prefix can be different for non-production envs
ASP_ITOU_PREFIX = "99999"
