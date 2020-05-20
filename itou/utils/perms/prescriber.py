from django.conf import settings
from django.shortcuts import get_object_or_404

from itou.prescribers.models import PrescriberOrganization


def get_current_org_or_404(request):
    pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
    queryset = PrescriberOrganization.objects.member_required(request.user)
    organization = get_object_or_404(queryset, pk=pk)
    return organization
