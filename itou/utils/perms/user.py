from collections import namedtuple

from django.conf import settings

from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_SIAE_STAFF = "siae_staff"
KIND_LABOR_INSPECTOR = "labor_inspector"

UserInfo = namedtuple("UserInfo", ["user", "kind", "prescriber_organization", "is_authorized_prescriber", "siae"])


def get_user_info(request):
    """
    Return a namedtuple containing information about the current logged user.
    """

    kind = None
    siae = None
    prescriber_organization = None

    if request.user.is_job_seeker:
        kind = KIND_JOB_SEEKER

    if request.user.is_siae_staff:
        kind = KIND_SIAE_STAFF
        siae = get_current_siae_or_404(request)

    if request.user.is_prescriber:
        kind = KIND_PRESCRIBER
        if request.user.is_prescriber_with_org:
            prescriber_organization = get_current_org_or_404(request)

    is_authorized_prescriber = prescriber_organization.is_authorized if prescriber_organization else False

    return UserInfo(request.user, kind, prescriber_organization, is_authorized_prescriber, siae)


def is_user_france_connected(request):
    """
    When a user logs in with France Connect, we store its france connect ID
    in the session. We can later know when a users logs in with France Connect
    """
    return settings.FRANCE_CONNECT_SESSION_TOKEN in request.session
