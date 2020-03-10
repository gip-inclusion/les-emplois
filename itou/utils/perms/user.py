from collections import namedtuple

from django.conf import settings
from django.shortcuts import get_object_or_404

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae

KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_SIAE_STAFF = "siae_staff"

UserInfo = namedtuple(
    "UserInfo",
    ["user", "kind", "prescriber_organization", "is_authorized_prescriber", "siae"],
)


def get_user_info(request):
    """
    Return a namedtuple containing information about the current logged user.
    """

    user = request.user
    kind = None
    prescriber_organization = None
    is_authorized_prescriber = False
    siae = None

    if request.user.is_job_seeker:
        kind = KIND_JOB_SEEKER

    if request.user.is_prescriber:
        kind = KIND_PRESCRIBER
        pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
        if pk:
            queryset = PrescriberOrganization.objects.member_required(user)
            prescriber_organization = get_object_or_404(queryset, pk=pk)
            is_authorized_prescriber = prescriber_organization.is_authorized

    if request.user.is_siae_staff:
        kind = KIND_SIAE_STAFF
        pk = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
        queryset = Siae.active_objects.member_required(user)
        siae = get_object_or_404(queryset, pk=pk)

    return UserInfo(user, kind, prescriber_organization, is_authorized_prescriber, siae)
