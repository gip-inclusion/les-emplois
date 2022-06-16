from collections import namedtuple

from itou.users import enums as users_enums
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


# FIXME(vperron): This namedtuple seems like an intermediate object that is maybe no longer justified.
# From afar it looks like a code smell or something we could/should get rid of. Beware.
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
