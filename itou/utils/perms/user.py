import logging

from hijack import signals


logger = logging.getLogger(__name__)


def has_hijack_perm(*, hijacker, hijacked):
    if not hijacker.is_active or not hijacked.is_active:
        return False

    # Staff members (especially superusers) shouldn't be hijacked
    if hijacked.is_staff or hijacked.is_superuser:
        return False

    # Superusers can do (almost) anything
    if hijacker.is_superuser:
        return True

    # Only whitelisted staff members can hijack other accounts
    if hijacker.is_staff and hijacker.has_perm("users.hijack_user"):
        return True

    return False


def hijack_started_signal(sender, hijacker, hijacked, request, **kwargs):
    logger.info("admin=%s has started impersonation of user=%s", hijacker.pk, hijacked.pk)


def hijack_ended_signal(sender, hijacker, hijacked, request, **kwargs):
    logger.info("admin=%s has ended impersonation of user=%s", hijacker.pk, hijacked.pk)


signals.hijack_started.connect(hijack_started_signal)
signals.hijack_ended.connect(hijack_ended_signal)
