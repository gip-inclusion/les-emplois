def can_view_personal_information(request, user):
    if can_edit_personal_information(request, user):  # If we can edit them then we can view them
        return True

    if user.is_job_seeker:  # Restrict display of personal information to job seeker
        if request.user.is_prescriber:
            if request.from_authorized_prescriber:
                return True
            else:
                return user.is_handled_by_proxy and user.is_created_by(request.user)
        elif request.user.is_employer:
            return True

    return False


def can_edit_personal_information(request, user):
    if request.user.pk == user.pk:  # I am me
        return True

    if request.user.is_prescriber:
        if request.from_authorized_prescriber:
            return user.is_handled_by_proxy
        else:
            return user.is_handled_by_proxy and user.is_created_by(request.user)
    elif request.user.is_employer:
        return user.is_handled_by_proxy

    return False
