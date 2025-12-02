from urllib.parse import urljoin

from django import template
from django.conf import settings

from itou.utils.urls import add_url_params


register = template.Library()


@register.simple_tag
def dora_service_url(service, *, mtm_campaign=None, mtm_kwd=None):
    if service["source"] == "dora" and service["lien_source"]:
        url = service["lien_source"]
    else:
        url = urljoin(settings.DORA_BASE_URL, f"/services/di--{service['id']}")
    if mtm_campaign and mtm_kwd:
        url = add_url_params(url, params={"mtm_campaign": mtm_campaign, "mtm_kwd": mtm_kwd})
    return url
