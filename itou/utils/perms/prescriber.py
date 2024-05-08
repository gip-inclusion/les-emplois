from django.db.models import Q
from django.http import Http404


def get_current_org_or_404(request):
    if request.user.is_prescriber and request.current_organization:  # Set by middleware for prescriber users
        return request.current_organization
    raise Http404("L'utilisateur n'est pas membre d'une organisation")


def get_all_available_job_applications_as_prescriber(request):
    """
    As a prescriber, I can have access to job_applications
    through my own user or through my organization.
    This helper filters the data accordingly.
    """
    from itou.job_applications.models import JobApplication

    if request.current_organization and request.user.is_prescriber:  # Set by middleware for prescriber users
        # Show all applications organization-wide + applications sent by the
        # current user for backward compatibility (in the past, a user could
        # create his prescriber's organization later on).
        return JobApplication.objects.filter(
            (Q(sender=request.user) & Q(sender_prescriber_organization__isnull=True))
            | Q(sender_prescriber_organization=request.current_organization)
        )
    else:
        return request.user.job_applications_sent
