"""
WSGI config for itou project.

It exposes the WSGI callable and is transmitted to Clever Cloud for deployment
via the environment variable `CC_PYTHON_MODULE=config.wsgi:application`.

Cf https://www.clever.cloud/developers/doc/reference/reference-environment-variables/#python
"""

import os

from django.core.wsgi import get_wsgi_application


if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise RuntimeError("DJANGO_SETTINGS_MODULE environment variable is not set.")

application = get_wsgi_application()
