import math

from django import template
from django.contrib.messages import constants as message_constants
from django.templatetags.static import static


register = template.Library()

URL_THEME = "vendor/theme-inclusion/"


@register.simple_tag
def static_theme(url_path):
    """
    Usage:
        {% load theme_inclusion %}
        {% static_theme url_path %}
    """
    return static(f"{URL_THEME}{url_path}")


@register.simple_tag
def static_theme_images(url_path):
    """
    Usage:
        {% load theme_inclusion %}
        {% static_theme_images url_path %}
    """
    return static(f"{URL_THEME}images/{url_path}")


TOAST_LEVEL_CLASSES = {
    message_constants.INFO: "toast--info",
    message_constants.SUCCESS: "toast--success",
    message_constants.WARNING: "toast--warning",
    message_constants.ERROR: "toast--danger",
}


@register.filter
def itou_toast_classes(message):
    return TOAST_LEVEL_CLASSES.get(message.level, "")


@register.filter
def itou_toast_title(message):
    return message.message.split("||", maxsplit=1)[0]


@register.filter
def itou_toast_content(message):
    try:
        return message.message.split("||", maxsplit=1)[1]
    except IndexError:
        return None


@register.filter
def stepper_progress(wizard):
    return math.floor((wizard["steps"].step1 / wizard["steps"].count) * 100)
