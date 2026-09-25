from django import template

from itou.www.constants import REDIRECTED_FROM_OLD_DOMAIN_KEY


register = template.Library()


@register.simple_tag
def redirected_from_old_domain(request):
    # When in MAINTENANCE_MODE, there is no session.
    session = getattr(request, "session", {})
    return REDIRECTED_FROM_OLD_DOMAIN_KEY in session
