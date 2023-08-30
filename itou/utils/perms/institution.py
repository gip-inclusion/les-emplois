from django.http import Http404


def get_current_institution_or_404(request):
    if request.user.is_labor_inspector and request.current_organization:  # Set by middleware for labor_inspector
        return request.current_organization
    raise Http404("L'utilisateur n'est pas membre d'une organisation")
