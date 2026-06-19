from itou.users.models import JobSeekerAssignment


def can_view_personal_information(request, user):
    """
    To view the personal information of another user, one must either be:
    - the user themselves
    - an authorized prescriber trying to view the personal info of a job seeker
    - an employer trying to view the personal info of a job seeker
    - a prescriber trying to view the personal info of a job seeker whose account they created
    """
    return _can_view_personal_information(
        request.user,
        user,
        is_allowed=request.from_authorized_prescriber or request.from_employer,
    )


def _can_view_personal_information(viewer, user, *, is_allowed):
    if _can_edit_personal_information(
        viewer, user, is_allowed=is_allowed
    ):  # If we can edit them then we can view them
        return True

    return user.is_job_seeker and viewer.is_professional and (is_allowed or user.is_created_by(viewer))


def can_edit_personal_information(request, user):
    """
    To edit the personal information of another user, one must either be:
    - the user themselves
    - an authorized prescriber trying to edit the personal info of a job seeker
    - an employer trying to edit the personal info of a job seeker
    - a prescriber trying to edit the personal info of a job seeker whose account they created
    """
    return _can_edit_personal_information(
        request.user,
        user,
        is_allowed=request.from_authorized_prescriber or request.from_employer,
    )


def _can_edit_personal_information(editor, user, *, is_allowed):
    if editor.pk == user.pk:  # I am me
        return True

    return user.is_job_seeker and editor.is_professional and (is_allowed or user.is_created_by(editor))


def can_view_last_advisor_contact_info(request, job_seeker):
    """
    To view the contact info of a job seeker's last known advisor, a user must either be:
    - the job seeker themselves
    - a professional involved in an assignment with the job seeker
    """
    if (
        job_seeker.is_job_seeker and request.user.pk == job_seeker.pk
    ):  # A job seeker can view the contact info of his last known advisor
        return True

    return (
        job_seeker.is_job_seeker
        and request.user.is_professional
        and (
            JobSeekerAssignment.objects.assigned_to(
                professional=request.user, organization=request.current_organization
            )
            .filter(job_seeker=job_seeker)
            .exists()
        )
    )
