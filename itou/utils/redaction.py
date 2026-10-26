"""Redaction helpers shared by the logging filters and the Sentry event scrubbers.

This module must stay free of Django imports: `config.sentry` imports it while
`config.settings` is still being loaded, before Django is set up.
"""

import re
import urllib.parse


REDACTED = "_REDACTED_"

# A whole `key=value` pair, so that the key can be tested on its own. A blank value is left
# alone: knowing that we sent an empty first name is what makes a 422 debuggable.
QUERY_PARAM_RE = re.compile(r"(?P<separator>^|[?&])(?P<key>[^&=\s'\"]+)=(?P<value>[^&\s'\"]+)")

# Query parameters kept readable by `redact_query_values_by_default`: which page, in which order, of
# which fields was asked for is what makes an outgoing call identifiable. For example,
# ?page=2&per_page=50&fields=id,name shows what was requested without saying about whom. Keep this
# list to keys that describe the shape of a query rather than its subject, and general enough that
# the next client can only use them the same way.
NON_PERSONAL_QUERY_KEYS = frozenset(
    {
        "champs",
        "extra",  # whether data.inclusion returns the producer-specific blob of each service
        "fields",
        "format",
        "kind",
        "limit",
        "offset",
        "order",
        "page",
        "page_size",
        "per_page",
        "realm",
        "size",
        "sort",
        "sources",  # which data.inclusion producers to import from
        "type",
    }
)

# A URL is recognized by its scheme and host, which is what tells an outgoing call apart from ours
_URL_WITH_QUERY_RE = re.compile(r"(?P<base>https?://[^\s'\"?]+\?)(?P<query>[^\s'\"]*)")

# Wherever it appears: in a log message, in the path of a URL (Brevo addresses a contact as
# /v3/contacts/someone@example.com), percent-encoded or not
_EMAIL_RE = re.compile(r"[\w.+%-]+(?:@|%40)(?:[\w-]+\.)+[A-Za-z]{2,}")


def redact_query_params(url):
    """Replace every query parameter value of an httpx.URL with a placeholder, keeping the keys.

    Example:
        `https://api.example.com/search?nom=Dupont&page=2`
        ➜ `https://api.example.com/search?nom=_REDACTED_&page=_REDACTED_`
    """
    return url.copy_with(params=[(key, REDACTED) for key, _value in url.params.multi_items()])


def redact_query_values(text, is_sensitive):
    """Replace the value of every query parameter whose key `is_sensitive`, keeping the keys.

    Works on a bare query string as well as on free text holding a URL, so that one rule covers
    the Sentry event and its breadcrumbs.

    Example:
        With `is_sensitive` true for `nom` only:
        `nom=Dupont&page=2` ➜ `nom=_REDACTED_&page=2`
    """

    def redact(match):
        # `prenoms%5B%5D` and `prenoms[]` are the same parameter, and both reach us
        if is_sensitive(urllib.parse.unquote(match["key"])):
            return f"{match['separator']}{match['key']}={REDACTED}"
        return match[0]

    return QUERY_PARAM_RE.sub(redact, text)


def redact_query_values_by_default(query_string):
    """Replace every value of a query string with a placeholder, save the few that name no one.

    For a query string that is not an `httpx.URL`: a bare `http.query`, or the query part of a
    URL found in free text. Redacting by default is what covers a client added tomorrow without
    touching any list.

    Example:
        `nom=Dupont&prenom=Jean&page=2` ➜ `nom=_REDACTED_&prenom=_REDACTED_&page=2`
    """
    return redact_query_values(query_string, lambda key: key.lower() not in NON_PERSONAL_QUERY_KEYS)


def redact_emails(text):
    """Redact every email address in `text`, which no rule on query parameters reaches.

    Example:
        `No Brevo contact for jean.dupont@example.com` ➜ `No Brevo contact for _REDACTED_`
    """
    return _EMAIL_RE.sub(REDACTED, text)


def redact_urls_in_text(text):
    """Redact the query string of every URL in `text`, whatever its parameters are.

    Our own request is not affected: Sentry stores it as a `url` without the query and a
    `query_string` without the host, so neither can match the scheme and host this looks for,
    and the filters of our own pages stay readable. A full URL of ours quoted elsewhere, in the
    `Referer` header or a `next` parameter, is redacted like an outgoing one.

    Example:
        `GET https://api.example.com/search?nom=Dupont&page=2 failed`
        ➜ `GET https://api.example.com/search?nom=_REDACTED_&page=2 failed`
    """
    return _URL_WITH_QUERY_RE.sub(lambda match: match["base"] + redact_query_values_by_default(match["query"]), text)


def redact_personal_data(text):
    """Redact the email addresses and the query strings of the outgoing URLs found in `text`.

    Example:
        `Sync of jean@example.com failed: https://api.example.com/search?nom=Dupont`
        ➜ `Sync of _REDACTED_ failed: https://api.example.com/search?nom=_REDACTED_`
    """
    return redact_urls_in_text(redact_emails(text))
