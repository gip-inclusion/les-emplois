from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_safe

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.models import Assessment, LABELInfos
from itou.utils.auth import check_user
from itou.www.geiq_assessments_views.forms import CreateForm


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
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    current_siret = request.current_organization.siret
    campaign_label_infos = (
        LABELInfos.objects.filter(campaign__year=timezone.localdate().year - 1).select_related("campaign").first()
    )
    label_data = campaign_label_infos.data if campaign_label_infos else []
    for geiq_info in label_data:
        if current_siret in [geiq_info["siret"], *(antenna["siret"] for antenna in geiq_info["antennes"])]:
            break
    else:
        geiq_info = None

    if geiq_info is not None:
        create_form = CreateForm(antennas=geiq_info["antennes"], geiq_name=geiq_info["nom"])
    else:
        create_form = None

    context = {
        "campaign_label_infos": campaign_label_infos,
        "siret": current_siret,
        "geiq_info": geiq_info,
        "main_geiq_name": "",
        "create_form": create_form,
        "antennas": [],
    }
    return render(request, template_name, context)
