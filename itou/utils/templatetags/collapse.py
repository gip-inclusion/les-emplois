"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template


register = template.Library()


@register.filter
def collapse(field_value):
    """
    Add a collapse bootstrap class for a form input
    (block with animated toggle on visibility)
    Only needed for checkboxes (bs collapse is primarily designed for links or buttons)
    see: https://getbootstrap.com/docs/4.4/components/collapse/
    """
    return "show" if field_value else ""
