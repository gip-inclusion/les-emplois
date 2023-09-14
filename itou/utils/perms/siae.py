from django.http import Http404

from itou.siaes.models import Siae


def get_current_siae_or_404(request) -> Siae:  # Set by middleware for siae_staff
    if request.user.is_siae_staff and request.current_organization:
        return request.current_organization
    raise Http404("L'utilisateur n'est pas membre d'une organisation")
