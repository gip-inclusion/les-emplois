from django.shortcuts import get_object_or_404

from itou.siaes.models import Siae
from itou.utils import constants as global_constants


def get_current_siae_or_404(request, with_job_descriptions=False, with_job_app_score=False) -> Siae:
    pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY)
    queryset = Siae.objects.member_required(request.user)

    if with_job_descriptions:
        queryset = queryset.prefetch_job_description_through()

    if with_job_app_score:
        queryset = queryset.with_job_app_score()

    siae = get_object_or_404(queryset, pk=pk)
    return siae
