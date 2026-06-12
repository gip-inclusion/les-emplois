import logging

from hijack import signals


logger = logging.getLogger(__name__)


def has_hijack_perm(*, hijacker, hijacked):
    if any(
        [
            not hijacked.is_active,  # Don't hijack inactive user
            not hijacked.email,  # Don't hijack user with no email : our middlewares don't like it
            hijacked.is_staff,  # staff members shouldn't be hijacked
            hijacked.is_superuser,  # Superusers really shouldn't be hijacked
        ]
    ):
        return False

    # Superusers can do (almost) anything
    if hijacker.is_superuser:
        return True

    # Only whitelisted staff members can hijack other accounts
    if hijacker.is_staff and hijacker.has_perm("users.hijack"):
        return True

    return False


def hijack_started_signal(sender, hijacker, hijacked, request, **kwargs):
    logger.info("admin=%s has started impersonation of user=%s", hijacker.pk, hijacked.pk)


def hijack_ended_signal(sender, hijacker, hijacked, request, **kwargs):
    logger.info("admin=%s has ended impersonation of user=%s", hijacker.pk, hijacked.pk)


signals.hijack_started.connect(hijack_started_signal)
signals.hijack_ended.connect(hijack_ended_signal)
