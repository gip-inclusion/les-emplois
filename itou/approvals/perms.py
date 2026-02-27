import logging

from itou.job_applications.enums import JobApplicationState
from itou.users.models import User


logger = logging.getLogger(__name__)

PERMS_READ = "read"
PERMS_READ_AND_WRITE = "read_and_write"


def can_view_approval_details(request, approval):
    """
    To display an approval details, one must either be:
    - the approval job seeker
    - an authorized prescriber whose job seekers list contains the approval's job seeker
    - an employer with a sent or received job_application
    """
    if request.from_employer:
        if application_states := approval.user.job_applications.filter(
            to_company=request.current_organization,
        ).values_list("state", flat=True):
            # The employer has received an application and can access the approval detail
            if JobApplicationState.ACCEPTED in application_states:
                # The employer has even accepted an application: the action buttons are visible
                return PERMS_READ_AND_WRITE
            return PERMS_READ
        if approval.user.job_applications.prescriptions_of(request.user, request.current_organization).exists():
            return PERMS_READ
    elif request.user.is_prescriber:
        if (
            request.from_authorized_prescriber
            and User.objects.linked_job_seeker_ids(request.user, request.current_organization).exists()
        ):
            return PERMS_READ
    elif request.user.is_job_seeker:
        if approval.user == request.user:
            return PERMS_READ
    else:
        logger.exception("This should never happen")
    return None
