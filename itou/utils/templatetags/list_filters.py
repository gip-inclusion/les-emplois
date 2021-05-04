"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template


register = template.Library()


@register.filter(name="zip")
def zip_lists(list_a, list_b):
    """
    Same as the zip command, but for a template
    """
    return zip(list_a, list_b)
