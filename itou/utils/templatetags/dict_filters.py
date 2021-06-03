"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template


register = template.Library()


@register.filter
def get_dict_item(dictionary, key):
    """
    Find a dictionary value with a key as a variable.
    https://stackoverflow.com/a/8000091

    Usage:
        {% load dict_filters %}
        {{ dict|get_dict_item:key }}
    """
    return dictionary.get(key)


@register.filter
def lookup_dict_item(dictionary, key):
    """
    Usage:
        {% load dict_filters %}
        {{ dict|lookup:key }}
    """
    return dictionary[key]


@register.filter
def get_attribute(obj, key):
    """
    Usage:
        {% load dict_filters %}
        {{ obj|gettattr:key }}
    """
    return getattr(obj, key)
