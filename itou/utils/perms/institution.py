from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404

from itou.institutions.models import Institution


def get_current_institution_or_404(request):
    pk = request.session.get(settings.ITOU_SESSION_CURRENT_INSTITUTION_KEY)
    queryset = Institution.objects.member_required(request.user)
    institution = get_object_or_404(queryset, pk=pk)
    return institution
