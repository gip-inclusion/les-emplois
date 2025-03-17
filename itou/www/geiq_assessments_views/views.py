from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_safe

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.models import Assessment, LABELInfos
from itou.utils.auth import check_user


@require_safe
@check_user(lambda user: user.is_employer)
def list_for_geiq(request, template_name="geiq_assessments_views/list_for_geiq.html"):
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    assessments = Assessment.objects.filter(companies=request.current_organization).select_related("campaign")
    context = {
        "assessments": assessments,
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def create_assessment(request, template_name="geiq_assessments_views/create.html"):
    label_infos = (
        LABELInfos.objects.filter(campaign__year=timezone.localdate().year - 1).select_related("campaign").first()
    )
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    context = {"label_infos": label_infos, "main_geiq_name": "", "antennas": []}
    return render(request, template_name, context)
