import logging

from django import template
from django.conf import settings

from itou.utils.enums import ItouEnvironment


logger = logging.getLogger(__name__)
register = template.Library()


@register.simple_tag
def should_not_happen(error_message, *values):
    if settings.ITOU_ENVIRONMENT != ItouEnvironment.PROD:
        raise ValueError(error_message % values)
    logger.warning(error_message, *values)
