"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

from django import template


register = template.Library()


@register.simple_tag
def call_method(obj, method_name, *args):
    """
    Allows to pass arguments to model methods in Django templates.

    Usage:
        {% load call_method %}
        {% call_method obj 'method_name' argument %}
    """
    method = getattr(obj, method_name)
    return method(*args)
