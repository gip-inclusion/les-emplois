def sort_organizations(collection):
    return sorted(collection, key=lambda o: (o.kind, o.display_name))


def get_current_organization_and_perms(request):
    if request.user.is_authenticated:
        context, extra_context = {}, {}

        if getattr(request, "current_organization", None) is not None:
            if request.user.is_siae_staff:
                extra_context = get_context_siae(request)

            if request.user.is_prescriber:
                extra_context = get_context_prescriber(request)

            if request.user.is_labor_inspector:
                extra_context = get_context_institution(request)

        context.update(extra_context)
        return context

    return {}


def get_context_siae(request):
    return {
        "current_siae": request.current_organization,
        "user_is_siae_admin": request.is_current_organization_admin,
        "user_siaes": sort_organizations(request.organizations),
    }


def get_context_prescriber(request):
    return {
        "current_prescriber_organization": request.current_organization,
        "user_is_prescriber_org_admin": request.is_current_organization_admin,
        "user_prescriberorganizations": sort_organizations(request.organizations),
    }


def get_context_institution(request):
    return {
        "current_institution": request.current_organization,
        "user_is_institution_admin": request.is_current_organization_admin,
        "user_institutions": sort_organizations(request.organizations),
    }
