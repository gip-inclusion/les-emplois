"""
Base settings to build other settings files upon.
https://docs.djangoproject.com/en/dev/ref/settings
"""
import os

# Paths.
# ------------------------------------------------------------------------------

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '../..'))

APPS_DIR = os.path.abspath(os.path.join(ROOT_DIR, 'itou'))

# General.
# ------------------------------------------------------------------------------

SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

DEBUG = os.environ.get('DJANGO_DEBUG', False)

ALLOWED_HOSTS = []

SITE_ID = 1

# Apps.
# ------------------------------------------------------------------------------

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.gis',
]

THIRD_PARTY_APPS = [
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'anymail',
    'bootstrap4',
]

LOCAL_APPS = [
    'itou.utils',
    'itou.cities',
    'itou.siae',
    'itou.prescribers',
    'itou.users',
    'itou.accounts',
    'itou.home',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Middleware.
# ------------------------------------------------------------------------------

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# URLs.
# ------------------------------------------------------------------------------

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = 'config.wsgi.application'

# Templates.
# ------------------------------------------------------------------------------

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(APPS_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                # Django.
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Database.
# ------------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'NAME': os.environ.get('ITOU_POSTGRES_DATABASE_NAME', 'jepostule'),
        'USER': os.environ.get('ITOU_POSTGRES_USER', 'jepostule'),
        'PASSWORD': os.environ.get('ITOU_POSTGRES_PASSWORD', 'mdp'),
    }
}

ATOMIC_REQUESTS = True

# Password validation.
# ------------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization.
# ------------------------------------------------------------------------------

LANGUAGE_CODE = 'fr-FR'

TIME_ZONE = 'Europe/Paris'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images).
# ------------------------------------------------------------------------------

# Path to the directory where collectstatic will collect static files for deployment.
STATIC_ROOT = os.path.join(APPS_DIR, 'static_collected')

STATIC_URL = '/static/'

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.CachedStaticFilesStorage'

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
)

STATICFILES_DIRS = (
    os.path.join(APPS_DIR, 'static'),
)

# Security.
# ------------------------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True

CSRF_COOKIE_HTTPONLY = True

SECURE_BROWSER_XSS_FILTER = True

X_FRAME_OPTIONS = "DENY"

SECURE_CONTENT_TYPE_NOSNIFF = True

# Logging.
# https://docs.djangoproject.com/en/dev/topics/logging
#----------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
        'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
        },
        'itou': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'DEBUG'),
        },
    },
}

# Email.
# https://anymail.readthedocs.io/en/stable/esps/mailjet/
# ------------------------------------------------------------------------------

EMAIL_BACKEND = 'anymail.backends.mailjet.EmailBackend'

ANYMAIL = {
    'MAILJET_API_KEY': os.environ['API_MAILJET_KEY'],
    'MAILJET_SECRET_KEY': os.environ['API_MAILJET_SECRET'],
}

MAILJET_API_URL = 'https://api.mailjet.com/v3'

DEFAULT_FROM_EMAIL = 'noreply@itou.beta.gouv.fr'

# Auth.
# https://django-allauth.readthedocs.io/en/latest/configuration.html
# ------------------------------------------------------------------------------

AUTH_USER_MODEL = 'users.User'

AUTHENTICATION_BACKENDS = (
    # Needed to login by username in Django admin.
    'django.contrib.auth.backends.ModelBackend',
    # `allauth` specific authentication methods, such as login by e-mail.
    'allauth.account.auth_backends.AuthenticationBackend',
)

LOGIN_REDIRECT_URL = '/accounts/dashboard'

ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_USER_DISPLAY = 'itou.users.models.get_allauth_account_user_display'

# APIs.
# ------------------------------------------------------------------------------

# Base Adresse Nationale (BAN).
# https://adresse.data.gouv.fr/faq
API_BAN_BASE_URL = 'https://api-adresse.data.gouv.fr'

# https://api.gouv.fr/api/api-geo.html#doc_tech
API_GEO_BASE_URL = 'https://geo.api.gouv.fr'

# Sirene - V3
# https://api.insee.fr/catalogue/
# https://github.com/sne3ks/api_insee
# > Autorise 30 requêtes par minute pour chaque application des utilisateurs.
# > Quota par défaut pour tout nouveau compte.
API_INSEE_KEY = os.environ['API_INSEE_KEY']
API_INSEE_SECRET = os.environ['API_INSEE_SECRET']

# Itou.
# ------------------------------------------------------------------------------

ITOU_EMAIL_CONTACT = 'contact@itou.beta.gouv.fr'

# Départements d'expérimentation :
# Pas-de-Calais (62), Bas-Rhin (67), Seine Saint Denis (93).
ITOU_TEST_DEPARTMENTS = ['62', '67', '93']
