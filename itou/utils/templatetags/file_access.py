from django import template
from sentry_sdk.api import capture_exception


register = template.Library()


@register.filter
def can_open_file(file):
    if not file:
        return False
    try:
        with file.open():
            return True
    except FileNotFoundError as e:
        capture_exception(e)
        return False
