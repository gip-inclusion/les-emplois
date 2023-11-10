from django.http import Http404

from itou.companies.models import Company


def get_current_company_or_404(request) -> Company:  # Set by middleware for employer
    if request.user.is_employer and request.current_organization:
        return request.current_organization
    raise Http404("L'utilisateur n'est pas membre d'une organisation")
