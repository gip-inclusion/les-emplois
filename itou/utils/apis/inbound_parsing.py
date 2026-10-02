import secrets
import string
from collections import namedtuple

from django.conf import settings

from itou.api.inbound_parsing.enums import InboundParsingKind
from itou.utils.apis.exceptions import InboundParsingValueError


InboundParsingIdentifier = namedtuple("InboundParsingIdentifier", ["key", "kind"])


def generate_key(length=20):
    """
    Generates an alphanumeric id to be used in the inbound parsing email addresses.
    """
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for i in range(length))


def generate_inbound_parsing_address(kind: InboundParsingKind, key=None):
    """
    Generates an email address with a random key and InboundParsingKind suffix.
    """
    if key is None:
        key = generate_key()
    return f"{key}_{kind.value}@{settings.INBOUND_PARSING_SUBDOMAIN}"


def get_inbound_parsing_address(email):
    """
    The documentations says Recipients is a list of Mailto (with an Address)
    but the given example says Recipients is a list of strings.
    https://developers.brevo.com/docs/inbound-parse-webhooks#parsed-email-payload
    """
    for recipient in email["Recipients"]:
        if isinstance(recipient, str):
            if f"@{settings.INBOUND_PARSING_SUBDOMAIN}".casefold() in recipient.casefold():
                return recipient.casefold()
        elif address := recipient.get("Address"):
            if f"@{settings.INBOUND_PARSING_SUBDOMAIN}".casefold() in address.casefold():
                return address.casefold()
    raise InboundParsingValueError("Unable to find inbound parsing address.")


def parse_inbound_parsing_address(address):
    """
    Parse email addresses of the form: <random_key>_<kind_value>@<inbound_parsing_domain>.
    Returns a InboundParsingIdentifier(key, kind).
    """
    username = address.split("@")[0]
    try:
        [key, kind] = username.split("_")
    except ValueError as e:
        raise InboundParsingValueError("Unable to parse inbound parsing address.") from e
    return InboundParsingIdentifier(key, kind)
