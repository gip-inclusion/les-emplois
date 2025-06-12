"""
WSGI config for itou project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import logging
import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application


logger = logging.getLogger("__name__")


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

if wsgi_db_statement_timeout := os.environ.get("WSGI_DB_STATEMENT_TIMEOUT"):
    os.environ["DB_STATEMENT_TIMEOUT"] = wsgi_db_statement_timeout
    if settings.configured:
        # Typically via runserver command, the wsgi app is loaded after the settings
        logger.warning("WSGI_DB_STATEMENT_TIMEOUT ignored: settings already configured.")

application = get_wsgi_application()
