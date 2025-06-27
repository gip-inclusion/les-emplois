from django import template
from django.apps import apps
from django.conf import settings


register = template.Library()


@register.simple_tag()
def enums(app_name, enum_name):
    enum_module = getattr(apps.get_app_config(app_name).module, "enums")
    enum_class = getattr(enum_module, enum_name)
    if settings.DEBUG:
        assert getattr(enum_class, "do_not_call_in_templates", False), (
            f"{enum_module}.{enum_class}.do_not_call_in_templates is not set"
        )
    return enum_class
