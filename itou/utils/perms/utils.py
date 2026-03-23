def can_view_personal_information(request, user):
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

    return (
        user.is_job_seeker
        and viewer.is_professional
        and (is_allowed or (user.is_handled_by_proxy and user.is_created_by(viewer)))
    )


def can_edit_personal_information(request, user):
    return _can_edit_personal_information(
        request.user,
        user,
        is_allowed=request.from_authorized_prescriber or request.from_employer,
    )


def _can_edit_personal_information(editor, user, *, is_allowed):
    if editor.pk == user.pk:  # I am me
        return True

    return (
        user.is_job_seeker
        and editor.is_professional
        and user.is_handled_by_proxy
        and (is_allowed or user.is_created_by(editor))
    )
