import logging
from collections import namedtuple

from django.conf import settings
from hijack import signals

from itou.users import enums as users_enums
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


logger = logging.getLogger(__name__)

# FIXME(vperron): This namedtuple seems like an intermediate object that is maybe no longer justified.
# From afar it looks like a code smell or something we could/should get rid of. Beware.
# (ikarius) : same verdict, this tuple is reused for eligibility diagnosis creation, and will have to be removed
# or at least limited to permissions domain.
UserInfo = namedtuple("UserInfo", ["user", "kind", "prescriber_organization", "is_authorized_prescriber", "siae"])


def get_user_info(request):
    """
    Return a namedtuple containing information about the current logged user.
    """

    kind = None
    siae = None
    prescriber_organization = None

    if request.user.is_job_seeker:
        kind = users_enums.KIND_JOB_SEEKER

    if request.user.is_siae_staff:
        kind = users_enums.KIND_SIAE_STAFF
        siae = get_current_siae_or_404(request)

    if request.user.is_prescriber:
        kind = users_enums.KIND_PRESCRIBER
        if request.user.is_prescriber_with_org:
            prescriber_organization = get_current_org_or_404(request)

    is_authorized_prescriber = prescriber_organization.is_authorized if prescriber_organization else False

    return UserInfo(request.user, kind, prescriber_organization, is_authorized_prescriber, siae)


def has_hijack_perm(*, hijacker, hijacked):
    if not hijacker.is_active or not hijacked.is_active:
        return False

    if hijacker.is_superuser:
        return True

    if not hijacker.is_staff:
        return False

    return hijacker.email.lower() in settings.HIJACK_ALLOWED_USER_EMAILS


def hijack_started_signal(sender, hijacker, hijacked, request, **kwargs):  # pylint: disable=unused-argument
    logger.info("admin=%s has started impersonation of user=%s", hijacker, hijacked)


def hijack_ended_signal(sender, hijacker, hijacked, request, **kwargs):  # pylint: disable=unused-argument
    logger.info("admin=%s has ended impersonation of user=%s", hijacker, hijacked)


signals.hijack_started.connect(hijack_started_signal)
signals.hijack_ended.connect(hijack_ended_signal)
