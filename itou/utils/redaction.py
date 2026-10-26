"""Redaction helpers shared by the logging filters and the Sentry event scrubbers.

This module must stay free of Django imports: `config.sentry` imports it while
`config.settings` is still being loaded, before Django is set up.
"""

REDACTED = "_REDACTED_"


def redact_query_params(url):
    """Replace every query parameter value of an httpx.URL with a placeholder, keeping the keys.

    Example:
        `https://api.example.com/search?nom=Dupont&page=2`
        ➜ `https://api.example.com/search?nom=_REDACTED_&page=_REDACTED_`
    """
    return url.copy_with(params=[(key, REDACTED) for key, _value in url.params.multi_items()])
