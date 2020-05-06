from collections import namedtuple

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_SIAE_STAFF = "siae_staff"

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
        siae = Siae.get_current_siae_or_404(request)

    if request.user.is_prescriber:
        kind = KIND_PRESCRIBER
        prescriber_organization = PrescriberOrganization.get_current_org_or_404(request, return_none_if_not_set=True)

    is_authorized_prescriber = prescriber_organization.is_authorized if prescriber_organization else False

    return UserInfo(request.user, kind, prescriber_organization, is_authorized_prescriber, siae)
