from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404

from itou.prescribers.models import PrescriberOrganization


def get_current_org_or_404(request):
    pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
    queryset = PrescriberOrganization.objects.member_required(request.user)
    organization = get_object_or_404(queryset, pk=pk)
    return organization


def get_all_available_job_applications_as_prescriber(request):
    """
    As a prescriber, I can have access to job_applications
    through my own user our through my organization.
    This helper filters the data accordingly.
    """
    from itou.job_applications.models import JobApplication

    if request.user.is_prescriber_with_org:
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
