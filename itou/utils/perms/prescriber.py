from django.db.models import Q
from django.shortcuts import get_object_or_404

from itou.prescribers.models import PrescriberOrganization
from itou.utils import constants as global_constants


def get_current_org_or_404(request):
    pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
    queryset = PrescriberOrganization.objects.member_required(request.user)
    organization = get_object_or_404(queryset, pk=pk)
    return organization


def get_all_available_job_applications_as_prescriber(request):
    """
    As a prescriber, I can have access to job_applications
    through my own user or through my organization.
    This helper filters the data accordingly.
    """
    from itou.job_applications.models import JobApplication

    if request.current_organization and request.user.is_prescriber:  # Set by middleware for prescriber users
        prescriber_organization = get_current_org_or_404(request)
        # Show all applications organization-wide + applications sent by the
        # current user for backward compatibility (in the past, a user could
        # create his prescriber's organization later on).
        return JobApplication.objects.filter(
            (Q(sender=request.user) & Q(sender_prescriber_organization__isnull=True))
            | Q(sender_prescriber_organization=prescriber_organization)
        )
    else:
        return request.user.job_applications_sent
