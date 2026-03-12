from urllib.parse import urljoin, urlsplit, urlunsplit

from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from itou.utils.urls import add_url_params


register = template.Library()


@register.simple_tag
def dora_service_url(service, *, orientation_jwt, source):
    if service["source"] == "dora" and service["lien_source"]:
        service_url = service["lien_source"]
        # FIXME: Choose if we want to keep it or not, but for now this will be used to
        #  not have prod URLs in our review app when testing `op` parameter and auto_login.
        if not url_has_allowed_host_and_scheme(service_url, settings.DORA_BASE_URL):
            service_url_parts = urlsplit(service_url)
            dora_url_parts = urlsplit(settings.DORA_BASE_URL)
            service_url = urlunsplit(dora_url_parts[:2] + service_url_parts[2:])
    else:
        service_url = urljoin(settings.DORA_BASE_URL, f"/services/di--{service['id']}")
    params = {"mtm_campaign": "lesemplois", "mtm_kwd": "rechservice-" + source}
    if orientation_jwt:
        params["op"] = orientation_jwt
    service_url = add_url_params(service_url, params=params)
    # The orientation_jwt is only present for ProConnect-ed users.
    if orientation_jwt:
        service_url = reverse("nexus:auto_login", query={"next_url": service_url})
    return service_url
