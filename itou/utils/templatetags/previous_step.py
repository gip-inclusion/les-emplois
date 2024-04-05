from urllib.parse import urlsplit

from django import template
from django.template.defaultfilters import stringfilter


register = template.Library()


@register.filter
@stringfilter
def is_list(url):
    url_info = urlsplit(url)
    url_path_last_part = url_info.path.split("/")[-1]
    return url_path_last_part.endswith(("list", "results"))
