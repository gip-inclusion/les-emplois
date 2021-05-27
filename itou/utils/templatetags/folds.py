"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template


register = template.Library()


@register.filter
def fold_class(field_value):
    """
    Add a bootstrap class in a "fold", i.e. paragraph with toggle on visibility
    """
    return "" if field_value else "d-none"
