from django.http import Http404

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization


def get_current_org_or_404(request) -> PrescriberOrganization:
    if request.from_prescriber and request.current_organization:  # Set by middleware for prescriber users
        return request.current_organization
    raise Http404("L'utilisateur n'est pas membre d'une organisation")


def is_authorized_ft_prescriber(request):
    return request.from_authorized_prescriber and request.current_organization.kind == PrescriberOrganizationKind.FT
