from urllib.parse import urljoin

from django import template
from django.conf import settings

from itou.utils.urls import add_url_params


register = template.Library()


@register.simple_tag
def dora_service_url(service, *, source):
    if service["source"] == "dora" and service["lien_source"]:
        url = service["lien_source"]
    else:
        url = urljoin(settings.DORA_BASE_URL, f"/services/di--{service['id']}")
    return add_url_params(url, params={"mtm_campaign": "lesemplois", "mtm_kwd": "rechservice-" + source})
