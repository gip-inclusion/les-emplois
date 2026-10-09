import secrets
import string

from django.conf import settings


def generate_key(length=15):
    """
    Generates an alphanumeric id to be used in the inbound parsing email addresses.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for i in range(length))


def generate_inbound_parsing_address(kind, key=None):
    """
    Generates an email address with a random key and InboundParsingKind suffix.
    """
    if key is None:
        key = generate_key()
    return f"{key}_{kind.value}@{settings.INBOUND_PARSING_SUBDOMAIN}"
