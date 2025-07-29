import logging

from itou.users.models import User


logger = logging.getLogger(__name__)


def can_view_approval_details(request, approval):
    """
    To display an approval details, one must either be:
    - the approval job seeker
    - an authorized prescriber
    - an employer with a sent or received job_application
    """
    if request.user.is_employer:
        return (
            approval.user.job_applications.filter(to_company=request.current_organization).exists()
            or approval.user.job_applications.prescriptions_of(request.user, request.current_organization).exists()
        )
    if request.user.is_prescriber:
        return (
            request.from_authorized_prescriber
            and User.objects.linked_job_seeker_ids(request.user, request.current_organization).exists()
        )
    if request.user.is_job_seeker:
        return approval.user == request.user
    logger.exception("This should never happen")
    return False
