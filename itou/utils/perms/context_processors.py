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
    return {}


def get_context_prescriber(request):
    return {}


def get_context_institution(request):
    return {}
