"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
from django import template
from django.templatetags.static import static
from django.utils.safestring import mark_safe


register = template.Library()

URL_THEME = "vendor/theme-inclusion/"

CSS_DEPENDENCIES_THEME = [
    {
        # for knwo it's dependecies only for c1
        "is_external": True,
        "src": "https://cdn.jsdelivr.net/npm/jquery-ui_1.12@1.12.0/jquery-ui.min.css",
        "integrity": "sha256-NRYg+xSNb5bHzrFEddJ0wL3YDp6YNt2dGNI+T5rOb2c=",
    },
    {
        "is_external": False,
        "src": "stylesheets/app.css",
    },
]


JS_DEPENDENCIES_THEME = [
    {
        "is_external": True,
        # "src": "https://code.jquery.com/jquery-3.5.1.slim.min.js", => could'nt work for us (C1)
        "src": "https://cdn.jsdelivr.net/npm/jquery@3.4.1/dist/jquery.min.js",
        "integrity": "sha256-CSXorXvZcTkaix6Yvo6HppcZGetbYMGWSFlBw8HfCJo=",
    },
    {
        # for knwo it's dependecies only for c1
        "is_external": True,
        "src": "https://cdn.jsdelivr.net/npm/jquery-ui_1.12@1.12.0/jquery-ui.min.js",
        "integrity": "sha256-eGE6blurk5sHj+rmkfsGYeKyZx3M4bG+ZlFyA7Kns7E=",
    },
    {
        "is_external": True,
        "src": "https://cdn.jsdelivr.net/npm/bootstrap@4.6.0/dist/js/bootstrap.bundle.min.js",
        "integrity": "sha384-Piv4xVNRyMGpqkS2by6br4gNJ7DXjqk09RmUpJ8jgGtD7zP9yug3goQfGII0yAns",
    },
    {
        "is_external": False,
        "src": "javascripts/app.js",
    },
    {
        "is_external": True,
        "src": "https://cdn.jsdelivr.net/npm/tarteaucitronjs@1.9.3/tarteaucitron.min.js",
        "integrity": "",
    },
]


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


@register.simple_tag
def import_static_CSS_theme_inclusion():
    scripts_import = ""
    for css_dep in CSS_DEPENDENCIES_THEME:
        if css_dep["is_external"]:
            scripts_import += (
                '<link rel="stylesheet" href="{}" integrity="{}" crossorigin="anonymous" type="text/css">'.format(
                    css_dep["src"], css_dep["integrity"]
                )
            )
        else:
            scripts_import += '<link rel="stylesheet" href="{}" type="text/css">'.format(static_theme(css_dep["src"]))
    return mark_safe(scripts_import)


@register.simple_tag
def import_static_JS_theme_inclusion():
    scripts_import = ""
    for js_dep in JS_DEPENDENCIES_THEME:
        if js_dep["is_external"]:
            scripts_import += '<script src="{}" integrity="{}" crossorigin="anonymous"></script>'.format(
                js_dep["src"], js_dep["integrity"]
            )
        else:
            scripts_import += '<script src="{}"></script>'.format(static_theme(js_dep["src"]))
    return mark_safe(scripts_import)
