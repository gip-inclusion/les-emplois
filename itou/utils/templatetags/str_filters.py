"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

import re
import string

from django import template
from django.template import defaultfilters


register = template.Library()


@register.filter(is_safe=False)
def pluralizefr(value, arg="s"):
    """
    Return a plural suffix if the value is greater than 1
    NB : the basic django pluralize filter returns the plural suffix for value==0
    """
    try:
        return arg if float(value) > 1 else ""
    except ValueError:  # Invalid string that's not a number.
        pass
    except TypeError:  # Value isn't a string or a number; maybe it's a list?
        try:
            return arg if len(value) > 1 else ""
        except TypeError:  # len() of unsized object.
            pass
    return ""


@register.filter(is_safe=True)
@defaultfilters.stringfilter
def mask_unless(value, predicate):
    if predicate:
        return value

    return " ".join(part[0] + "…" for part in re.split(f"[{re.escape(string.whitespace)}]+", value) if part)


@register.filter
def addstr(arg1, arg2):
    """concatenate arg1 & arg2"""
    return str(arg1) + str(arg2)
