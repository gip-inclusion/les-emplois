"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

import io
import re
from textwrap import wrap

from django import template
from django.template.defaultfilters import stringfilter
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe


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
    nir_without_spaces = nir.replace(" ", "")
    nir_regex = r"^([12])([0-9]{2})([0-9]{2})(2[AB]|[0-9]{2})([0-9]{3})([0-9]{3})([0-9]{2})$"
    match = re.match(nir_regex, nir_without_spaces)
    if match is not None:
        groups = match.groups()
        with io.StringIO() as formatted:
            formatted.write(f"<span>{groups[0]}</span>")
            for group in groups[1:]:
                formatted.write(f'<span class="ms-1">{group}</span>')
            return mark_safe(formatted.getvalue())
    else:
        # Some NIRs do not match the pattern (they can be NTT/NIA) so we can’t format them
        # When this happen, we should not crash but return the initial value
        return nir


@register.filter(needs_autoescape=True)
@stringfilter
def format_approval_number(number, autoescape=True):
    if not number:
        return ""
    group_indices = [[0, 5], [5, 7], [7, None]]
    escape = conditional_escape if autoescape else lambda text: text
    parts = [escape(number[start:end]) for start, end in group_indices]
    return mark_safe(
        f'<span>{parts[0]}</span><span class="ms-1">{parts[1]}</span><span class="ms-1">{parts[2]}</span>'
    )


@register.filter
@stringfilter
def remove_json_extension(filename):
    return filename.removesuffix(".json")
