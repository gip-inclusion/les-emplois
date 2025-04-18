from django.http import Http404

from itou.prescribers.models import PrescriberOrganization


def get_current_org_or_404(request) -> PrescriberOrganization:
    if request.user.is_prescriber and request.current_organization:  # Set by middleware for prescriber users
        return request.current_organization
    raise Http404("L'utilisateur n'est pas membre d'une organisation")
