from django import template

from itou.utils import constants


register = template.Library()


@register.simple_tag
def pilotage_public_dashboard(slug, **kwargs):
    return f"{constants.PILOTAGE_SITE_URL}/tableaux-de-bord/{slug}/"
