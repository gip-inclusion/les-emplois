"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template
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
    static_path = "{base_url}{url_path}".format(base_url=URL_THEME, url_path=url_path)
    return static(static_path)


@register.simple_tag
def static_theme_images(url_path):
    """
    Usage:
        {% load theme_inclusion %}
        {% static_theme_images url_path %}
    """
    static_path = "{base_url}images/{url_path}".format(base_url=URL_THEME, url_path=url_path)
    return static(static_path)
