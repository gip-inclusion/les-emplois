import io
import logging
import operator
import uuid

from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Prefetch
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST, require_safe

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, REGIONS
from itou.companies.enums import CompanyKind
from itou.files.models import File
from itou.geiq import sync
from itou.geiq_assessments.models import Assessment, AssessmentInstitutionLink, EmployeeContract, LabelInfos
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.utils.apis import geiq_label
from itou.utils.auth import check_user
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url
from itou.www.geiq_assessments_views.forms import ActionFinancialAssessmentForm, CreateForm, GeiqCommentForm


logger = logging.getLogger(__name__)


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
        LabelInfos.objects.filter(campaign__year=timezone.localdate().year - 1).select_related("campaign").first()
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

    conflicting_antennas = []
    if request.method == "POST" and create_form and create_form.is_valid():
        label_antennas = []
        if create_form.cleaned_data.get("main_geiq"):
            label_antennas.append({"id": 0, "name": geiq_info["nom"]})
        for antenna_id, antenna_name in antenna_names.items():
            if create_form.cleaned_data.get(create_form.get_antenna_field(antenna_id)):
                label_antennas.append({"id": antenna_id, "name": antenna_name})

        # Check existing assessments
        for existing_assessment in Assessment.objects.filter(
            campaign=campaign_label_infos.campaign,
            label_geiq_id=geiq_info["id"],
        ).only("label_antennas"):
            existing_antenna_ids = existing_assessment.label_antenna_ids()
            for antenna in label_antennas:
                if antenna["id"] in existing_antenna_ids:
                    conflicting_antennas.append(antenna)

        if not conflicting_antennas:
            ddets = create_form.cleaned_data["ddets"]
            dreets = create_form.cleaned_data["dreets"]
            name_for_geiq_parts = []
            if dreets:
                name_for_geiq_parts.append(f"DREETS {dreets.region}")
            if ddets:
                name_for_geiq_parts.append(f"DDETS {ddets.department}")

            assessment = Assessment.objects.create(
                campaign=campaign_label_infos.campaign,
                name_for_institution=geiq_info["nom"],
                name_for_geiq="/".join(name_for_geiq_parts),
                label_geiq_id=geiq_info["id"],
                label_antennas=sorted(
                    label_antennas, key=operator.itemgetter("id")
                ),  # Stable order to detect duplicates
            )

            # TODO: link companies matching the selected SIRET
            # petit risque si un malin se crée une antenne avec le SIRET d'une antenne GEIQ connue
            # ajouter le lien vers la fiche entreprise pour indiquer que l'antenne est connue des emplois ?
            assessment.companies.add(request.current_organization)
            ddets_dreets = (
                Institution.objects.filter(
                    kind=InstitutionKind.DREETS_GEIQ, department__in=REGIONS[DEPARTMENT_TO_REGION[ddets.department]]
                ).first()
                if ddets
                else None
            )
            if ddets:
                AssessmentInstitutionLink.objects.create(
                    assessment=assessment, institution=ddets, with_convention=True
                )

            if dreets:
                AssessmentInstitutionLink.objects.create(
                    assessment=assessment, institution=dreets, with_convention=True
                )
            if ddets_dreets and ddets_dreets != dreets:
                AssessmentInstitutionLink.objects.create(
                    assessment=assessment, institution=ddets_dreets, with_convention=False
                )
            return HttpResponseRedirect(reverse("geiq_assessments_views:details", kwargs={"pk": assessment.pk}))

    context = {
        "conflicting_antennas": conflicting_antennas,
        "campaign_label_infos": campaign_label_infos,
        "geiq_info": geiq_info,
        "siret": current_siret,
        "form": create_form,
    }
    return render(request, template_name, context)


class AssessmentDetailsTab(models.TextChoices):
    MAIN = "main", "Mon dossier"
    KPI = "kpi", "Indicateurs clés"
    RESULT = "result", "Résultat"


@check_user(lambda user: user.is_employer)
def assessment_details(request, pk, template_name="geiq_assessments_views/assessment_details.html"):
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    assessment = Assessment.objects.prefetch_related(
        Prefetch(
            "institution_links",
            queryset=AssessmentInstitutionLink.objects.select_related("institution").order_by("institution__kind"),
        )
    ).get(companies=request.current_organization.pk, pk=pk)

    if request.method == "POST":
        assessment.submitted_at = timezone.now()
        assessment.submitted_by = request.user
        assessment.save(update_fields=("submitted_at", "submitted_by"))
        return HttpResponseRedirect(reverse("geiq_assessments_views:details", kwargs={"pk": assessment.pk}))

    context = {
        "assessment": assessment,
        "back_url": reverse("geiq_assessments_views:list_for_geiq"),
        "matomo_custom_title": "Bilan d’exécution - page de detail",
        "active_tab": AssessmentDetailsTab.MAIN,
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer or user.is_labor_inspector)
def assessment_get_file(request, pk, *, file_field):
    if request.user.is_employer:
        filter_kwargs = {"companies": request.current_organization}
    elif request.user.is_labor_inspector:
        filter_kwargs = {"institutions": request.current_organization}
    else:
        raise Http404  # This should never happen thanks to check_user
    assessments = Assessment.objects.filter(**filter_kwargs).select_related("campaign")
    assessment = get_object_or_404(assessments, pk=pk)
    match file_field:
        case "summary_document_file":
            filename = assessment.summary_document_filename()
        case "structure_financial_assessment_file":
            filename = assessment.structure_financial_assessment_filename()
        case "action_financial_assessment_file":
            filename = assessment.action_financial_assessment_filename()
        case _:
            raise Http404
    return HttpResponseRedirect(
        default_storage.url(
            getattr(assessment, Assessment._meta.get_field(file_field).attname),
            parameters={
                "ResponseContentDisposition": content_disposition_header("inline", filename),
            },
        )
    )


@require_POST
@check_user(lambda user: user.is_employer)
def assessment_sync_file(request, pk, *, file_field):
    assessments = Assessment.objects.filter(companies=request.current_organization)
    assessment = get_object_or_404(assessments, pk=pk)

    context = {"assessment": assessment}
    match file_field:
        case "summary_document_file":
            api_method = "get_synthese_pdf"
            template_name = "geiq_assessments_views/includes/summary_document_section.html"
        case "structure_financial_assessment_file":
            api_method = "get_compte_pdf"
            template_name = "geiq_assessments_views/includes/structure_financial_assessment_section.html"
        case _:
            raise Http404
    try:
        client = geiq_label.get_client()
        pdf_content = getattr(client, api_method)(geiq_id=assessment.label_geiq_id)
        key = default_storage.save(f"{uuid.uuid4()}.pdf", io.BytesIO(pdf_content))
        setattr(assessment, file_field, File.objects.create(key=key))
        assessment.save(update_fields=(file_field,))
    except Exception as e:
        # (ImproperlyConfigured, geiq_label.LabelAPIError) are expected
        # but letting other exceptions slip breaks the interface so better catch them all
        logger.exception(
            "Exception while trying to retrieve a pdf from label API - field=%s exception=%s", file_field, e
        )
        context["error"] = True
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def upload_action_financial_assessment(
    request, pk, template_name="geiq_assessments_views/action_financial_assessment_upload.html"
):
    assessments = Assessment.objects.filter(companies=request.current_organization)
    assessment = get_object_or_404(assessments, pk=pk)
    back_url = get_safe_url(
        request, "back_url", fallback_url=reverse("geiq_assessments_views:details", kwargs={"pk": assessment.pk})
    )
    form = ActionFinancialAssessmentForm(data=request.POST or None, files=request.FILES or None)
    context = {
        "assessment": assessment,
        "form": form,
        "back_url": back_url,
    }
    if request.method == "POST" and form.is_valid():
        assessment_pdf = form.cleaned_data["assessment_file"]
        file_key = default_storage.save(str(uuid.uuid4()), assessment_pdf)
        assessment.action_financial_assessment_file = File.objects.create(key=file_key)
        assessment.save(update_fields=("action_financial_assessment_file",))
        return HttpResponseRedirect(back_url)
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def assessment_comment(request, pk, template_name="geiq_assessments_views/assessment_comment.html"):
    assessments = Assessment.objects.filter(companies=request.current_organization)
    assessment = get_object_or_404(assessments, pk=pk)
    back_url = get_safe_url(
        request, "back_url", fallback_url=reverse("geiq_assessments_views:details", kwargs={"pk": assessment.pk})
    )
    form = GeiqCommentForm(instance=assessment, data=request.POST or None)
    context = {
        "assessment": assessment,
        "form": form,
        "back_url": back_url,
    }
    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(back_url)
    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer)
def assessment_contracts_sync(request, pk):
    assessments = Assessment.objects.filter(companies=request.current_organization)
    assessment = get_object_or_404(assessments, pk=pk)

    context = {"assessment": assessment, "active_tab": AssessmentDetailsTab.MAIN}
    try:
        sync.sync_employee_and_contracts(assessment, new_mode=True)
        # TODO: sync label data to db & update assessment.label_contracts_synced_at
    except Exception as e:
        # (ImproperlyConfigured, geiq_label.LabelAPIError) are expected
        # but letting other exceptions slip breaks the interface so better catch them all
        logger.exception("Exception while trying to retrieve contracts infos from label API - exception=%s", e)
        context["error"] = True
    return render(request, "geiq_assessments_views/includes/contracts_section.html", context)


@check_user(lambda user: user.is_employer or user.is_labor_inspector)
def assessment_contracts_list(request, pk, template_name="geiq_assessments_views/assessment_contracts_list.html"):
    # TODO: should this part be extracted in a `for_request() queryset method ?
    contract_filter_kwargs = {}
    if request.user.is_employer:
        filter_kwargs = {"companies": request.current_organization}
    elif request.user.is_labor_inspector:
        filter_kwargs = {"institutions": request.current_organization, "submitted_at__isnull": False}
        contract_filter_kwargs = {"allowance_requested": True}
    else:
        raise Http404  # This should never happen thanks to check_user
    assessments = Assessment.objects.filter(**filter_kwargs)
    assessment = get_object_or_404(assessments, pk=pk)

    back_url, readonly_access = None, False
    if request.user.is_employer:
        back_url = reverse("geiq_assessments_views:details", kwargs={"pk": assessment.pk})
        readonly_access = assessment.submitted_at
    elif request.user.is_labor_inspector:
        back_url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        readonly_access = assessment.reviewed_at
    if request.method == "POST" and not readonly_access:
        if request.user.is_employer:
            assessment.contracts_selection_validated_at = timezone.now()
            assessment.save(update_fields=("contracts_selection_validated_at",))
        elif request.user.is_labor_inspector:
            assessment.grants_selection_validated_at = timezone.now()
            assessment.save(update_fields=("grants_selection_validated_at",))
        return HttpResponseRedirect(back_url)

    contracts_page = pager(
        EmployeeContract.objects.filter(employee__assessment=assessment, **contract_filter_kwargs)
        .select_related("employee__assessment")
        .order_by("employee__first_name", "employee__last_name"),
        request.GET.get("page"),
        items_per_page=10,
    )
    context = {
        "assessment": assessment,
        "back_url": back_url,
        "contracts_page": contracts_page,
        "readonly_access": readonly_access,
        "AssessmentContractDetailsTab": AssessmentContractDetailsTab,
    }
    return render(request, template_name, context)


class AssessmentContractDetailsTab(models.TextChoices):
    EMPLOYEE = "employee", "Informations salarié"
    CONTRACT = "contract", "Contrat"
    SUPPORT_AND_TRAINING = "support-and-training", "Accompagnement et formation"
    EXIT = "exit", "Sortie"


@check_user(lambda user: user.is_employer)
def assessment_contracts_details(
    request, contract_pk, tab, template_name="geiq_assessments_views/assessment_contracts_details.html"
):
    try:
        details_tab = AssessmentContractDetailsTab(tab)
    except ValueError:
        raise Http404
    contract_qs = EmployeeContract.objects.filter(
        employee__assessment__companies=request.current_organization
    ).select_related("employee__assessment__campaign")
    if details_tab == AssessmentContractDetailsTab.SUPPORT_AND_TRAINING:
        contract_qs = contract_qs.prefetch_related("employee__prequalifications")
    contract = get_object_or_404(contract_qs, pk=contract_pk)
    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse(
            "geiq_assessments_views:assessment_contracts_list", kwargs={"pk": contract.employee.assessment.pk}
        ),
    )
    context = {
        "back_url": back_url,
        "assessment": contract.employee.assessment,
        "contract": contract,
        "matomo_custom_title": "Bilan d’exécution - page de detail d’un contrat",
        "AssessmentContractDetailsTab": AssessmentContractDetailsTab,
        "active_tab": details_tab,
    }
    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer or user.is_labor_inspector)
def _assessment_contracts_toggle(
    request, contract_pk, new_value, template_name="geiq_assessments_views/includes/contracts_switch.html"
):
    if request.user.is_employer:
        filter_kwargs = {"employee__assessment__companies": request.current_organization}
    elif request.user.is_labor_inspector:
        filter_kwargs = {
            "employee__assessment__institutions": request.current_organization,
            "employee__assessment__submitted_at__isnull": False,
        }
    else:
        raise Http404  # This should never happen thanks to check_user
    contract = get_object_or_404(
        EmployeeContract.objects.filter(**filter_kwargs)
        .select_related("employee__assessment")
        .select_for_update(of=("self",)),
        pk=contract_pk,
    )
    assessment = contract.employee.assessment
    if request.user.is_employer and not assessment.submitted_at and contract.allowance_requested != new_value:
        contract.allowance_requested = new_value
        contract.save(update_fields=("allowance_requested",))
        if assessment.contracts_selection_validated_at:
            assessment.contracts_selection_validated_at = None
            assessment.save(update_fields=("contracts_selection_validated_at",))
    elif request.user.is_labor_inspector and not assessment.reviewed_at and contract.allowance_granted != new_value:
        contract.allowance_granted = new_value
        contract.save(update_fields=("allowance_granted",))
        if assessment.grants_selection_validated_at:
            assessment.grants_selection_validated_at = None
            assessment.save(update_fields=("grants_selection_validated_at",))
    context = {
        "assessment": assessment,
        "contract": contract,
        "from_list": bool(request.GET.get("from_list")),
        "readonly_access": False,
        "value": new_value,
    }
    return render(request, template_name, context)


@require_safe
@check_user(lambda user: user.is_employer)
def assessment_kpi(request, pk, template_name="geiq_assessments_views/assessment_kpi.html"):
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    assessment = Assessment.objects.filter(contracts_synced_at__isnull=False).get(
        companies=request.current_organization.pk, pk=pk
    )

    context = {
        "assessment": assessment,
        "back_url": reverse("geiq_assessments_views:list_for_geiq"),
        "matomo_custom_title": "Bilan d’exécution - onglet des indicateurs clés",
        "AssessmentDetailsTab": AssessmentDetailsTab,
        "active_tab": AssessmentDetailsTab.KPI,
    }
    return render(request, template_name, context)


@require_safe
@check_user(lambda user: user.is_labor_inspector)
def list_for_institution(request, template_name="geiq_assessments_views/list_for_institution.html"):
    if request.current_organization.kind not in (InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ):
        raise Http404
    assessments = Assessment.objects.filter(institutions=request.current_organization).select_related("campaign")
    context = {
        "assessments": assessments,
    }
    return render(request, template_name, context)


class AssessmentContractDetailsForInstitutionTab(models.TextChoices):
    FILE = "file", "Dossier transmis par le GEIQ"
    CONTRACTS = "contracts", "Données salariés"


@require_safe
@check_user(lambda user: user.is_labor_inspector)
def details_for_institution(
    request, pk, template_name="geiq_assessments_views/assessment_details_for_institution.html"
):
    if request.current_organization.kind not in (InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ):
        raise Http404
    assessments = Assessment.objects.filter(institutions=request.current_organization).select_related("campaign")
    assessment = get_object_or_404(assessments, pk=pk)
    context = {
        "assessment": assessment,
        "active_tab": AssessmentContractDetailsForInstitutionTab.FILE,
        "back_url": reverse("geiq_assessments_views:list_for_institution"),
    }
    return render(request, template_name, context)


# review_assessment
# contracts_include_for_institution
# contracts_exclude_for_institution
