import logging

from itou.job_applications.enums import JobApplicationState
from itou.users.models import User
from itou.utils.tokens import prolongation_derogation_token_generator


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
    elif request.from_prescriber:
        if (
            request.from_authorized_prescriber
            and User.objects.assigned_job_seeker_ids(request.user, request.current_organization).exists()
        ):
            return PERMS_READ
    elif request.user.is_job_seeker:
        if approval.user == request.user:
            return PERMS_READ
    else:
        logger.exception("This should never happen")
    return None


def prolongation_derogation_session_key(*, approval, company):
    """Where the token of a derogation link is kept for the duration of the declaration flow."""
    return f"prolongation_derogation:{company.pk}:{approval.pk}"


def can_declare_prolongation(request, *, approval, company):
    """Whether `company` may open the prolongation form for `approval`.

    A derogation link issued by the support for this exact (approval, company) pair waives the
    prolongation deadline (`Approval.prolongation_period_has_ended`), and only this limit: an
    approval that is suspended, that is not the latest one of the job seeker, that already has a
    pending prolongation request or that ends in more than 12 months still cannot be prolonged.

    Following such a link stores its token in the session, see the `prolongation_derogation`
    view. The token is checked again here on every step of the flow, and remains single-use:
    declaring a prolongation consumes it, see `ProlongationDerogationTokenGenerator`.
    """
    if not company.is_subject_to_iae_rules:
        return False
    if approval.can_be_prolonged:
        return True
    if not approval.needs_prolongation_derogation:
        return False
    token = request.session.get(prolongation_derogation_session_key(approval=approval, company=company))
    return prolongation_derogation_token_generator.check_token(token, approval=approval, company=company)
