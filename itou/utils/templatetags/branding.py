"""https://docs.djangoproject.com/en/dev/howto/custom-template-tags/"""

from django import template

from itou.utils.brand import product_name


register = template.Library()


@register.simple_tag
def brand(prep=None):
    return product_name(prep)
