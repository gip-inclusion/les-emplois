from django.shortcuts import get_object_or_404

from itou.siaes.models import Siae
from itou.utils import constants as global_constants


def get_current_siae_or_404(request) -> Siae:
    pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
    queryset = Siae.objects.member_required(request.user)

    siae = get_object_or_404(queryset, pk=pk)
    return siae
