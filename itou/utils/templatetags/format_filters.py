"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""
import re
from textwrap import wrap

from django import template
from django.template.defaultfilters import stringfilter


register = template.Library()


@register.filter
@stringfilter
def format_phone(phone_number):
    """
    Usage:
        {% load format_filters %}
        {{ user.phone|format_phone }}
    """
    if not phone_number:
        return ""
    return " ".join(wrap(phone_number, 2))


@register.filter
@stringfilter
def format_siret(siret):
    """
    Format SIREN and SIRET
    Example: 12345678901234 => 123 456 789 00123
    """
    if len(siret) < 9:
        # Don't format invalid SIREN/SIRET
        return siret

    siren = f"{siret[0:3]} {siret[3:6]} {siret[6:9]}"
    if len(siret) == 9:
        return siren

    return f"{siren} {siret[9:]}"


@register.filter
@stringfilter
def format_nir(nir):
    nir = nir.replace(" ", "")
    nir_regex = r"^([12])([0-9]{2})([0-9]{2})(2[AB]|[0-9]{2})([0-9]{3})([0-9]{3})([0-9]{2})$"
    match = re.match(nir_regex, nir)
    return " ".join(match.groups())
