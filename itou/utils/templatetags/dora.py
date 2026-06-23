from urllib.parse import urljoin, urlsplit

from django import template
from django.conf import settings
from django.urls import reverse

from itou.insertion.models import Service
from itou.utils.urls import add_url_params


register = template.Library()


@register.simple_tag
def dora_orientation_url(service: Service, *, orientation_jwt: str | None, source: str) -> str:
    if service.source.value == "dora" and service.source_link:
        slug = urlsplit(service.source_link).path.rstrip("/").split("/")[-1]
        orientation_url = urljoin(settings.DORA_WWW_BASE_URL, f"/services/{slug}/orienter")
    else:
        orientation_url = urljoin(settings.DORA_WWW_BASE_URL, f"/services/di--{service.uid}/orienter")
    params = {"mtm_campaign": "lesemplois", "mtm_kwd": "service-" + source}
    if orientation_jwt:
        params["op"] = orientation_jwt
    orientation_url = add_url_params(orientation_url, params=params)
    if orientation_jwt:
        orientation_url = reverse("nexus:auto_login", query={"next_url": orientation_url})
    return orientation_url
