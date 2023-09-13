import logging

from django.conf import settings
from hijack import signals


logger = logging.getLogger(__name__)


def has_hijack_perm(*, hijacker, hijacked):
    if not hijacker.is_active or not hijacked.is_active:
        return False

    if hijacker.is_superuser:
        return True

    if not hijacker.is_staff:
        return False

    return hijacker.email.lower() in settings.HIJACK_ALLOWED_USER_EMAILS


def hijack_started_signal(sender, hijacker, hijacked, request, **kwargs):
    logger.info("admin=%s has started impersonation of user=%s", hijacker, hijacked)


def hijack_ended_signal(sender, hijacker, hijacked, request, **kwargs):
    logger.info("admin=%s has ended impersonation of user=%s", hijacker, hijacked)


signals.hijack_started.connect(hijack_started_signal)
signals.hijack_ended.connect(hijack_ended_signal)
