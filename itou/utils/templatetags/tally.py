from django import template

from itou.utils.urls import get_tally_form_url


register = template.Library()


@register.simple_tag
def tally_form_url(form_id, **kwargs):
    """
    Wraps `itou.utils.urls.get_tally_form_url` for template usage.
    Can use context variables.

    Usage in template  : {% tally_form_url "tally_form_id" my_param=some_context_var ... %}
    """
    return get_tally_form_url(form_id, **kwargs)
