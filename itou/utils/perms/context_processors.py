def get_current_organization_and_perms(request):
    context = {}
    if request.user.is_authenticated and getattr(request, "current_organization", None) is not None:
        if request.user.is_siae_staff:
            context = get_context_siae(request)
        elif request.user.is_prescriber:
            context = get_context_prescriber(request)
        elif request.user.is_labor_inspector:
            context = get_context_institution(request)
    return context


def get_context_siae(request):
    return {
        "current_siae": request.current_organization,
        "user_is_siae_admin": request.is_current_organization_admin,
        "user_siaes": request.organizations,
    }


def get_context_prescriber(request):
    return {
        "current_prescriber_organization": request.current_organization,
        "user_is_prescriber_org_admin": request.is_current_organization_admin,
        "user_prescriberorganizations": request.organizations,
    }


def get_context_institution(request):
    return {
        "current_institution": request.current_organization,
        "user_is_institution_admin": request.is_current_organization_admin,
        "user_institutions": request.organizations,
    }
