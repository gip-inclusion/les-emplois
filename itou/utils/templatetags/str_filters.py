"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

import re
import string
import textwrap

from django import template
from django.template import defaultfilters
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter(is_safe=False)
def pluralizefr(value, arg="s"):
    """
    This is the Django's pluralize filter code, adapted to match French rules.
    (NB : the basic django pluralize filter returns the plural suffix for value==0)
    """
    if "," not in arg:
        arg = "," + arg
    bits = arg.split(",")
    if len(bits) > 2:
        return ""
    singular_suffix, plural_suffix = bits[:2]

    try:
        return singular_suffix if float(value) <= 1 else plural_suffix
    except ValueError:  # Invalid string that's not a number.
        pass
    except TypeError:  # Value isn't a string or a number; maybe it's a list?
        try:
            return singular_suffix if len(value) <= 1 else plural_suffix
        except TypeError:  # len() of unsized object.
            pass
    return ""


@register.filter(is_safe=True)
@defaultfilters.stringfilter
def mask_unless(value, predicate, mask_function=(lambda x: x[0] + "…")):
    if predicate:
        return value

    return " ".join(mask_function(part) for part in re.split(f"[{re.escape(string.whitespace)}]+", value) if part)


@register.filter(is_safe=False)
@defaultfilters.stringfilter
def shorten(value, width):
    return textwrap.shorten(value, width=width, placeholder=" …")


@register.filter
def split_literal_newlines(value: str) -> list[str]:
    """Splits a string on literal \\n sequences (as found in text imported from DI)."""
    return [line for line in value.split("\\n") if line]


@register.filter(is_safe=True)
@defaultfilters.stringfilter
def urlize_new_tab(value: str) -> str:
    """Like |urlize but opens links in a new tab with rel="noopener noreferrer"."""
    urlized = defaultfilters.urlize(value)
    result = re.sub(r"<a ", '<a target="_blank" rel="noopener noreferrer" ', urlized)
    return mark_safe(result)
