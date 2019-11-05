"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template


register = template.Library()


@register.filter
def dict_lookup(value, arg):
    """
    Usage:
        {% load dict_lookup %}
        {{ mydict|dict_lookup:item.name }}
    """
    return value.get(arg)
