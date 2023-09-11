from django.shortcuts import get_object_or_404

from itou.institutions.models import Institution
from itou.utils import constants as global_constants


def get_current_institution_or_404(request):
    pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
    queryset = Institution.objects.member_required(request.user)
    institution = get_object_or_404(queryset, pk=pk)
    return institution
