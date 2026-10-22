import secrets
import string
from collections import namedtuple

from django.conf import settings

from itou.api.inbound_parsing.enums import InboundParsingKind
from itou.utils.apis.exceptions import InboundParsingValueError


InboundParsingIdentifier = namedtuple("InboundParsingIdentifier", ["kind", "key"])


def generate_key(length=20):
    """
    Generates an alphanumeric id to be used in the inbound parsing email addresses.
    """
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for i in range(length))


def generate_inbound_parsing_address(kind: InboundParsingKind, key=None):
    """
    Generates an email address with a random key and an InboundParsingKind suffix.
    """
    if key is None:
        key = generate_key()
    return f"{kind.value}.{key}@{settings.INBOUND_PARSING_SUBDOMAIN}"


def get_parsed_inbound_parsing_address(email):
    """
    The documentation says Recipients is a list of Mailto (with an Address)
    but the given example says Recipients is a list of strings.
    https://developers.brevo.com/docs/inbound-parse-webhooks#parsed-email-payload

    Returns an InboundParsingIdentifier(key, kind) if an email in Recipients has
    the form: <kind_value>.<random_key>@<inbound_parsing_domain>.
    """
    suffix = f"@{settings.INBOUND_PARSING_SUBDOMAIN}".casefold()
    address = ""
    for recipient in email["Recipients"]:
        candidate = recipient if isinstance(recipient, str) else (recipient.get("Address") or "")
        if suffix in candidate.casefold():
            address = candidate.casefold()
            break
    if not address:
        raise InboundParsingValueError("Unable to find inbound parsing address.")

    username = address.split("@")[0]
    try:
        [kind, key] = username.split(".")
    except ValueError as e:
        raise InboundParsingValueError("Unable to parse inbound parsing address.") from e
    return InboundParsingIdentifier(kind, key)
