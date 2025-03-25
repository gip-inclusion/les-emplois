import operator

from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_safe

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, REGIONS
from itou.companies.enums import CompanyKind
from itou.geiq_assessments.models import Assessment, AssessmentInstitutionLink, LABELInfos
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
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
    for geiq_data in label_data:
        if current_siret in [geiq_data["siret"], *(antenna["siret"] for antenna in geiq_data["antennes"])]:
            geiq_info = geiq_data
            break
    else:
        geiq_info = None

    if geiq_info is not None:
        antenna_names = {antenna_info["id"]: antenna_info["nom"] for antenna_info in geiq_info["antennes"]}
        create_form = CreateForm(antenna_names=antenna_names, geiq_name=geiq_info["nom"], data=request.POST or None)
    else:
        create_form = None

    if request.method == "POST" and create_form and create_form.is_valid():
        # TODO: store antenna selection
        label_antennas = []
        if create_form.cleaned_data.get("main_geiq"):
            label_antennas.append({"id": 0, "name": geiq_info["nom"]})
        for antenna_id, antenna_name in antenna_names.items():
            if create_form.cleaned_data.get(create_form.get_antenna_field(antenna_id)):
                label_antennas.append({"id": antenna_id, "name": antenna_name})

        assessment = Assessment.objects.create(
            campaign=campaign_label_infos.campaign,
            name_for_institution=geiq_info["nom"],
            label_geiq_id=geiq_info["id"],
            label_antennas=sorted(label_antennas, key=operator.itemgetter("id")),  # Stable order to detect duplicates
        )

        # TODO: link companies matching the selected SIRET
        # petit risque si un malin se crée une antenne avec le SIRET d'une antenne GEIQ connue
        # ajouter le lien vers la fiche entreprise pour indiquer que l'antenne est connue des emplois ?
        assessment.companies.add(request.current_organization)
        ddets = create_form.cleaned_data["ddets"]
        ddets_dreets = (
            Institution.objects.filter(
                kind=InstitutionKind.DREETS_GEIQ, department__in=REGIONS[DEPARTMENT_TO_REGION[ddets.department]]
            ).first()
            if ddets
            else None
        )
        dreets = create_form.cleaned_data["dreets"]
        if ddets:
            AssessmentInstitutionLink.objects.create(assessment=assessment, institution=ddets, with_convention=True)

        if dreets:
            AssessmentInstitutionLink.objects.create(assessment=assessment, institution=dreets, with_convention=True)
        if ddets_dreets and ddets_dreets != dreets:
            AssessmentInstitutionLink.objects.create(
                assessment=assessment, institution=ddets_dreets, with_convention=False
            )
        return HttpResponseRedirect(reverse("geiq_assessments_views:details", kwargs={"pk": assessment.pk}))

    context = {
        "campaign_label_infos": campaign_label_infos,
        "geiq_info": geiq_info,
        "siret": current_siret,
        "form": create_form,
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def assessment_details(request, pk, template_name="geiq_assessments_views/assessment_details.html"):
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    assessment = Assessment.objects.prefetch_related("institutions").get(
        companies=request.current_organization.pk, pk=pk
    )
    context = {
        "assessment": assessment,
    }
    return render(request, template_name, context)
