"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template
from django.utils.safestring import mark_safe


register = template.Library()


@register.simple_tag
def redirection_url(name, value):
    """
    Append a URL to be followed if needed.

    Usage:
        {% load redirection_fields %}
        '/my_url{% redirection_url name=redirect_field_name value=redirect_field_value %}''
    """
    if value:
        return f"?{name}={value}"
    return ""


@register.simple_tag
def redirection_input_field(name, value):
    """
    Return a form input field with a redirection URL if needed.

    Usage:
        {% load redirection_fields %}
        {% redirection_input_field name=redirect_field_name value=redirect_field_value %}
    """
    if value:
        return mark_safe(f'<input type="hidden" name="{name}" value="{value}">')
    return ""
