from django import template


register = template.Library()


@register.filter
def default_if_invalid(value, arg):
    if value == template.engines["django"].engine.string_if_invalid:  # Yes, it likely is the empty string ""
        return arg
    return value
