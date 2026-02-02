from urllib.parse import urljoin

from django import template
from django.conf import settings
from django.urls import reverse

from itou.utils.urls import add_url_params


register = template.Library()


@register.simple_tag
def dora_service_url(service, *, orientation_jwt, source):
    if service["source"] == "dora" and service["lien_source"]:
        service_url = service["lien_source"]
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
