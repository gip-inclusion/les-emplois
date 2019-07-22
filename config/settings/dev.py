from .base import *  # noqa

DEBUG = os.environ.get('DJANGO_DEBUG', True)

ALLOWED_HOSTS = ['localhost', '0.0.0.0', '127.0.0.1']

# Django-extensions.
# ------------------------------------------------------------------------------

INSTALLED_APPS += ['django_extensions']  # noqa F405

# Django-debug-toolbar.
# ------------------------------------------------------------------------------

INSTALLED_APPS += ['debug_toolbar']  # noqa F405

INTERNAL_IPS = ['127.0.0.1']

# Enable django-debug-toolbar with Docker.
import socket
_, _, ips = socket.gethostbyname_ex(socket.gethostname())
INTERNAL_IPS += [ip[:-1] + '1' for ip in ips]

MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']  # noqa F405

DEBUG_TOOLBAR_CONFIG = {
    'DISABLE_PANELS': ['debug_toolbar.panels.redirects.RedirectsPanel'],
    'SHOW_TEMPLATE_CONTEXT': True,
}
