from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme


KNOWN_DOMAINS = frozenset(
    [
        *settings.ALLOWED_HOSTS,
        "diagoriente.beta.gouv.fr",
        "cloud.info.afpa.fr",
    ]
)


def markdown_url_trusted_location(attrs, new=False):
    if href := attrs.get((None, "href")):
        if not url_has_allowed_host_and_scheme(href, allowed_hosts=KNOWN_DOMAINS):
            return None
    return attrs
