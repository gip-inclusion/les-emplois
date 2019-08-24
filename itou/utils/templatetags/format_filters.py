"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from textwrap import wrap

from django import template
from django.template.defaultfilters import stringfilter


register = template.Library()


@register.filter
@stringfilter
def format_phone(phone_number):
    if not phone_number:
        return ""
    return " ".join(wrap(phone_number, 2))
