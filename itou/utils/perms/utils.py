def can_view_personal_information(request, user):
    return _can_view_personal_information(
        request.user,
        user,
        viewer_is_prescriber_from_authorized_org=request.from_authorized_prescriber,
    )


def _can_view_personal_information(viewer, user, *, viewer_is_prescriber_from_authorized_org):
    if _can_edit_personal_information(
        viewer, user, editor_is_prescriber_from_authorized_org=viewer_is_prescriber_from_authorized_org
    ):  # If we can edit them then we can view them
        return True

    if user.is_job_seeker:  # Restrict display of personal information to job seeker
        if viewer.is_prescriber:
            if viewer_is_prescriber_from_authorized_org:
                return True
            else:
                return user.is_handled_by_proxy and user.is_created_by(viewer)
        elif viewer.is_employer:
            return True

    return False


def can_edit_personal_information(request, user):
    return _can_edit_personal_information(
        request.user,
        user,
        editor_is_prescriber_from_authorized_org=request.from_authorized_prescriber,
    )


def _can_edit_personal_information(editor, user, *, editor_is_prescriber_from_authorized_org):
    if editor.pk == user.pk:  # I am me
        return True

    if editor.is_prescriber:
        if editor_is_prescriber_from_authorized_org:
            return user.is_handled_by_proxy
        else:
            return user.is_handled_by_proxy and user.is_created_by(editor)
    elif editor.is_employer:
        return user.is_handled_by_proxy

    return False
