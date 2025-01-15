"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

from urllib.parse import urlsplit, urlunsplit

from django import template
from django.http import QueryDict

from itou.users.enums import IdentityProvider


register = template.Library()


@register.simple_tag
def url_add_query(url, **kwargs):
    """
    Append a querystring param to the given url.
    If the querystring param is already present it will be replaced
    otherwise it will be appended.

    Usage:
        {% load url_add_query %}
        {% url_add_query request.get_full_path page=2 %}
    """
    parsed = urlsplit(url)
    querystring = QueryDict(parsed.query, mutable=True)
    # Remove params with None or "" values
    cleaned_kwargs = {k: v for k, v in kwargs.items() if v is not None and v != ""}
    for item in cleaned_kwargs:
        if item in querystring:
            querystring.pop(item)
    querystring.update(cleaned_kwargs)
    return urlunsplit(parsed._replace(query=querystring.urlencode("/")))


@register.simple_tag
def autologin_proconnect(url, user):
    if user.is_authenticated and user.identity_provider == IdentityProvider.PRO_CONNECT:
        return url_add_query(url, proconnect_login="true")
    return url
