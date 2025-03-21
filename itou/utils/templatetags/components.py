from django import template
from slippers.templatetags.slippers import register_components


register = template.Library()

register_components({"component_title": "components/c-title.html"}, register)
