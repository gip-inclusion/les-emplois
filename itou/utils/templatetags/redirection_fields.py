"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

from django import template
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.utils.html import format_html


register = template.Library()


@register.simple_tag
def redirection_url(value):
    """
    Append a URL to be followed if needed.

    Usage:
        {% load redirection_fields %}
        '/my_url{% redirection_url value=redirect_field_value %}''
    """
    if value:
        return f"?{REDIRECT_FIELD_NAME}={value}"
    return ""


@register.simple_tag
def redirection_input_field(value):
    """
    Return a form input field with a redirection URL if needed.

    Usage:
        {% load redirection_fields %}
        {% redirection_input_field value=redirect_field_value %}
    """
    if value:
        return format_html('<input type="hidden" name="{}" value="{}">', REDIRECT_FIELD_NAME, value)
    return ""
