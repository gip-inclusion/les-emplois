import json

from django.template import Library
from django.utils.safestring import mark_safe


register = Library()


@register.filter(is_safe=True)
def js(obj):
    return mark_safe(json.dumps(obj))
