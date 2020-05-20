from django.conf import settings
from django.shortcuts import get_object_or_404

from itou.siaes.models import Siae


def get_current_siae_or_404(request):
    pk = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.objects.member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)
    return siae
