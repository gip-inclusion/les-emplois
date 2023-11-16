from django import template
from django.utils.html import format_html


register = template.Library()


@register.simple_tag
def matomo_event(category, action, option):
    return format_html(
        'data-matomo-event="true" data-matomo-category="{}" data-matomo-action="{}" data-matomo-option="{}"',
        category,
        action,
        option,
    )
