import secrets
import string

from django.conf import settings


def generate_key(length=10):
    """
    Generates an alphanumeric id to be used in the inbound parsing email addresses.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for i in range(length))


def generate_email(kind, key=None):
    if key is None:
        key = generate_key()
    return f"{kind.value}.{key}@{settings.INBOUND_PARSING_SUBDOMAIN}"
