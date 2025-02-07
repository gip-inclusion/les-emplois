import math

from django import template
from django.contrib.messages import constants as message_constants
from django.templatetags.static import static
from django_bootstrap5.templatetags.django_bootstrap5 import bootstrap_field


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
def stepper_progress(steps):
    return math.floor((steps.step1 / steps.count) * 100)


@register.simple_tag
def get_form_field(form, field_name):
    return form[field_name]


@register.simple_tag
def collapse_field(bound_field, *, target_id, **kwargs):
    """
    A bootstrap_field that toggles a collapse element.

    Using a custom template tag allows setting the data attributes directly in the template,
    next to where the field is rendered, for a better locality of behavior than specifying
    the attributes in the form.

    :arg django.forms.boundfield.BoundField bound_field: field to render with bootstrap_field
    :keyword str target_id: id attribute of the HTML element to collapse
    """
    field_spec = bound_field.field
    collapse_attrs = {
        "data-bs-toggle": "collapse",
        "data-bs-target": f"#{target_id}",
        "aria-controls": target_id,
    }
    for attr, value in collapse_attrs.items():
        if attr in field_spec.widget.attrs:
            raise NotImplementedError("The field must be present once on the page")
        field_spec.widget.attrs[attr] = value
    return bootstrap_field(bound_field, **kwargs)
