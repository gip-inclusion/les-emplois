def can_view_personal_information(request, user):
    return _can_view_personal_information(
        request.user,
        user,
        viewer_is_prescriber_from_authorized_org=request.from_authorized_prescriber,
        viewer_is_employer=request.from_employer,
    )


def _can_view_personal_information(viewer, user, *, viewer_is_prescriber_from_authorized_org, viewer_is_employer):
    if _can_edit_personal_information(
        viewer,
        user,
        editor_is_prescriber_from_authorized_org=viewer_is_prescriber_from_authorized_org,
        editor_is_employer=viewer_is_employer,
    ):  # If we can edit them then we can view them
        return True

    if user.is_job_seeker:  # Restrict display of personal information to job seeker
        if viewer.is_caseworker:
            if viewer_is_prescriber_from_authorized_org or viewer_is_employer:
                return True
            else:
                return user.is_handled_by_proxy and user.is_created_by(viewer)

    return False


def can_edit_personal_information(request, user):
    return _can_edit_personal_information(
        request.user,
        user,
        editor_is_prescriber_from_authorized_org=request.from_authorized_prescriber,
        editor_is_employer=request.from_employer,
    )


def _can_edit_personal_information(editor, user, *, editor_is_prescriber_from_authorized_org, editor_is_employer):
    if editor.pk == user.pk:  # I am me
        return True

    if editor.is_caseworker:
        if editor_is_prescriber_from_authorized_org or editor_is_employer:
            return user.is_handled_by_proxy
        else:
            return user.is_handled_by_proxy and user.is_created_by(editor)

    return False
