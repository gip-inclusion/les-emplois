import enum
import io
import logging
import operator
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Case, Count, F, Prefetch, Q, Sum, When
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST, require_safe

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, REGIONS
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.files.models import File
from itou.geiq import sync
from itou.geiq_assessments.models import (
    Assessment,
    AssessmentCampaign,
    AssessmentInstitutionLink,
    EmployeeContract,
    LabelInfos,
)
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.utils.apis import geiq_label
from itou.utils.auth import check_user
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url
from itou.www.geiq_assessments_views.forms import (
    ActionFinancialAssessmentForm,
    CreateForm,
    GeiqCommentForm,
    ReviewForm,
)


logger = logging.getLogger(__name__)


def company_has_access_to_assessments(company):
    return (
        company.kind == CompanyKind.GEIQ
        and any(settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES)
        and company.post_code.startswith(tuple(settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES))
    )


def get_allowance_stats_for_geiq(assessment, *, for_assessment_details=False):
    extra_stats = (
        {
            "contracts_nb": Count("pk"),
            "contracts_selected_nb": Count("pk", filter=Q(allowance_requested=True)),
            "allowance_of_0_selected_nb": Count(
                "pk", filter=Q(allowance_requested=True, employee__allowance_amount=0)
            ),
        }
        if not for_assessment_details
        else {}
    )
    return EmployeeContract.objects.filter(employee__assessment=assessment).aggregate(
        allowance_of_814_selected_nb=Count("pk", filter=Q(allowance_requested=True, employee__allowance_amount=814)),
        allowance_of_1400_selected_nb=Count("pk", filter=Q(allowance_requested=True, employee__allowance_amount=1400)),
        potential_allowance_amount=Sum("employee__allowance_amount", filter=Q(allowance_requested=True)),
        **extra_stats,
    )


def get_allowance_stats_for_institution(assessment, *, for_assessment_details=False):
    extra_stats = (
        {
            "apprenticeship_contracts_nb": Count("pk", filter=Q(other_data__nature_contrat__libelle_abr="CAPP")),
            "apprenticeship_contracts_selected_nb": Count(
                "pk", filter=Q(other_data__nature_contrat__libelle_abr="CAPP", allowance_granted=True)
            ),
            "professionalization_contracts_nb": Count("pk", filter=Q(other_data__nature_contrat__libelle_abr="CPRO")),
            "professionalization_contracts_selected_nb": Count(
                "pk", filter=Q(other_data__nature_contrat__libelle_abr="CPRO", allowance_granted=True)
            ),
            "contracts_with_3_months_in_assessment_year_nb": Count(
                "pk", filter=Q(with_3_months_in_assessment_year=True)
            ),
            "contracts_with_3_months_in_assessment_year_selected_nb": Count(
                "pk", filter=Q(with_3_months_in_assessment_year=True, allowance_granted=True)
            ),
        }
        if for_assessment_details
        else {
            "allowance_of_0_selected_nb": Count("pk", filter=Q(employee__allowance_amount=0, allowance_granted=True)),
        }
    )
    return EmployeeContract.objects.filter(employee__assessment=assessment, allowance_requested=True).aggregate(
        contracts_nb=Count("pk"),  # submitted contracts nb
        contracts_selected_nb=Count("pk", filter=Q(allowance_granted=True)),  # accepted contracts nb
        allowance_of_814_nb=Count("pk", filter=Q(employee__allowance_amount=814)),
        allowance_of_814_selected_nb=Count("pk", filter=Q(employee__allowance_amount=814, allowance_granted=True)),
        allowance_of_1400_nb=Count("pk", filter=Q(employee__allowance_amount=1400)),
        allowance_of_1400_selected_nb=Count("pk", filter=Q(employee__allowance_amount=1400, allowance_granted=True)),
        potential_allowance_amount=Sum("employee__allowance_amount", filter=Q(allowance_granted=True)),
        **extra_stats,
    )


@require_safe
@check_user(lambda user: user.is_employer)
def list_for_geiq(request, template_name="geiq_assessments_views/list_for_geiq.html"):
    if not company_has_access_to_assessments(request.current_organization):
        raise Http404
    assessments = (
        Assessment.objects.filter(companies=request.current_organization)
        .select_related("campaign")
        .prefetch_related(
            Prefetch(
                "institution_links",
                queryset=AssessmentInstitutionLink.objects.select_related("institution"),
            ),
        )
    )
    context = {
        "assessments": assessments,
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def create_assessment(request, template_name="geiq_assessments_views/create.html"):
    if not company_has_access_to_assessments(request.current_organization):
        raise Http404
    current_siret = request.current_organization.siret
    campaign_label_infos = LabelInfos.objects.filter(campaign__year=timezone.localdate().year - 1).first()
    label_data = campaign_label_infos.data if campaign_label_infos else []
    for geiq_data in label_data:
        if current_siret in [geiq_data["siret"], *(antenna["siret"] for antenna in geiq_data["antennes"])]:
            geiq_info = geiq_data
            break
    else:
        geiq_info = None

    context = {
        "siret": current_siret,
        "campaign_label_infos": campaign_label_infos,
        "geiq_info": geiq_info,
    }
    if geiq_info is None:
        return render(request, template_name, context)

    antenna_names = {antenna_info["id"]: antenna_info["nom"] for antenna_info in geiq_info["antennes"]}
    campaign_qs = AssessmentCampaign.objects.filter(pk=campaign_label_infos.campaign_id)
    # Take a lock on the campaign to prevent concurrent creation
    campaign = campaign_qs.select_for_update().get() if request.method == "POST" else campaign_qs.get()
    existing_antenna_ids = set()
    # Check existing assessments
    for existing_assessment in Assessment.objects.filter(campaign=campaign, label_geiq_id=geiq_info["id"]).only(
        "label_antennas"
    ):
        existing_antenna_ids.update(
            [antenna["id"] for antenna in existing_assessment.label_antennas]
            if existing_assessment.label_antennas
            else []
        )

    create_form = CreateForm(
        antenna_names=antenna_names,
        existing_antenna_ids=existing_antenna_ids,
        geiq_name=geiq_info["nom"],
        data=request.POST or None,
    )

    conflicting_antennas = create_form.conflicting_antennas()
    if request.method == "POST" and create_form and create_form.is_valid() and not conflicting_antennas:
        antenna_sirets = {antenna_info["id"]: antenna_info["siret"] for antenna_info in geiq_info["antennes"]}
        label_antennas = []
        sirets = set()
        if create_form.cleaned_data.get("main_geiq"):
            label_antennas.append({"id": 0, "name": geiq_info["nom"]})
            if geiq_siret := geiq_info["siret"]:
                sirets.add(geiq_siret)

        antenna_names = {antenna_info["id"]: antenna_info["nom"] for antenna_info in geiq_info["antennes"]}
        for antenna_id, antenna_name in antenna_names.items():
            if create_form.cleaned_data.get(create_form.get_antenna_field(antenna_id)):
                label_antennas.append({"id": antenna_id, "name": antenna_name})
                if antenna_siret := antenna_sirets[antenna_id]:
                    sirets.add(antenna_siret)

        ddets = create_form.cleaned_data["ddets"]
        dreets = create_form.cleaned_data["dreets"]

        assessment = Assessment.objects.create(
            created_by=request.user,
            campaign=campaign,
            name_for_institution=geiq_info["nom"],
            label_geiq_id=geiq_info["id"],
            label_antennas=sorted(label_antennas, key=operator.itemgetter("id")),  # Stable order to detect duplicates
        )
        assessment.companies.add(request.current_organization)
        for company in (
            Company.objects.filter(kind=CompanyKind.GEIQ, siret__in=filter(None, sirets))
            .exclude(pk=request.current_organization.pk)
            .all()
        ):
            assessment.companies.add(company)

        ddets_dreets = (
            Institution.objects.filter(
                kind=InstitutionKind.DREETS_GEIQ, department__in=REGIONS[DEPARTMENT_TO_REGION[ddets.department]]
            ).first()
            if ddets
            else None
        )
        if ddets:
            AssessmentInstitutionLink.objects.create(assessment=assessment, institution=ddets, with_convention=True)

        if dreets:
            AssessmentInstitutionLink.objects.create(assessment=assessment, institution=dreets, with_convention=True)
        if ddets_dreets and ddets_dreets != dreets:
            AssessmentInstitutionLink.objects.create(
                assessment=assessment, institution=ddets_dreets, with_convention=False
            )
        logger.info(
            "user=%s created assessment=%s", request.user.pk, assessment.pk, extra={"geiq_assessment": assessment.pk}
        )
        return HttpResponseRedirect(reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))

    context["conflicting_antennas"] = conflicting_antennas
    context["form"] = create_form
    return render(request, template_name, context)


class AssessmentDetailsTab(models.TextChoices):
    MAIN = "main", "Mon dossier"
    KPI = "kpi", "Indicateurs clés"
    RESULT = "result", "Résultat"


@check_user(lambda user: user.is_employer)
def assessment_details_for_geiq(request, pk, template_name="geiq_assessments_views/assessment_details_for_geiq.html"):
    if not company_has_access_to_assessments(request.current_organization):
        raise Http404
    assessment = get_object_or_404(
        Assessment.objects.select_related("campaign")
        .filter(companies=request.current_organization.pk)
        .prefetch_related(
            Prefetch(
                "institution_links",
                queryset=AssessmentInstitutionLink.objects.select_related("institution").order_by("institution__kind"),
            )
        ),
        pk=pk,
    )

    if request.method == "POST":
        assessment.submitted_at = timezone.now()
        assessment.submitted_by = request.user
        assessment.save(update_fields=("submitted_at", "submitted_by"))
        # Preselect all contracts for institution validation
        EmployeeContract.objects.filter(employee__assessment=assessment).update(
            allowance_granted=F("allowance_requested")
        )
        return HttpResponseRedirect(reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))

    context = {
        "assessment": assessment,
        "back_url": reverse("geiq_assessments_views:list_for_geiq"),
        "matomo_custom_title": "Bilan d’exécution - page de detail",
        "active_tab": AssessmentDetailsTab.MAIN,
        "PILOTAGE_INSTITUTION_EMAIL_CONTACT": settings.PILOTAGE_INSTITUTION_EMAIL_CONTACT,
    }
    if assessment.contracts_selection_validated_at:
        context["stats"] = get_allowance_stats_for_geiq(assessment, for_assessment_details=True)
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
            template_name = "geiq_assessments_views/includes/summary_document_box.html"
        case "structure_financial_assessment_file":
            api_method = "get_compte_pdf"
            template_name = "geiq_assessments_views/includes/structure_financial_assessment_box.html"
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
        request,
        "back_url",
        fallback_url=reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
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
        request,
        "back_url",
        fallback_url=reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
    )
    form = GeiqCommentForm(instance=assessment, data=request.POST or None)
    context = {
        "assessment": assessment,
        "form": form,
        "back_url": back_url,
    }
    if request.method == "POST" and form.is_valid():
        form.save()
        logger.info(
            "user=%s updated the comment of assessment=%s",
            request.user.pk,
            assessment.pk,
            extra={"geiq_assessment": assessment.pk},
        )
        return HttpResponseRedirect(back_url)
    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer)
def assessment_contracts_sync(request, pk):
    assessments = Assessment.objects.filter(companies=request.current_organization)
    assessment = get_object_or_404(assessments, pk=pk)

    context = {"assessment": assessment, "active_tab": AssessmentDetailsTab.MAIN}
    try:
        context["assessment"] = sync.sync_employee_and_contracts(assessment, new_mode=True)
    except Exception as e:
        # (ImproperlyConfigured, geiq_label.LabelAPIError) are expected
        # but letting other exceptions slip breaks the interface so better catch them all
        logger.exception("Exception while trying to retrieve contracts infos from label API - exception=%s", e)
        context["error"] = True
    return render(request, "geiq_assessments_views/includes/contracts_box.html", context)


class ContractsAction(enum.StrEnum):
    VALIDATE = "validate"
    UNVALIDATE = "unvalidate"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


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

    back_url, can_validate, can_unvalidate, stats = None, False, False, None  # defined to please the linters
    if request.user.is_employer:
        back_url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        if not assessment.submitted_at:
            can_validate = not assessment.contracts_selection_validated_at
            can_unvalidate = not can_validate
    elif request.user.is_labor_inspector:
        back_url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        if not assessment.reviewed_at:
            can_validate = not assessment.grants_selection_validated_at
            can_unvalidate = not can_validate
    if request.method == "POST":
        try:
            action = ContractsAction(request.POST.get("action"))
        except ValueError:
            raise Http404
        if action == ContractsAction.VALIDATE:
            if not can_validate:
                raise PermissionDenied
            if request.user.is_employer:
                assessment.contracts_selection_validated_at = timezone.now()
                assessment.save(update_fields=("contracts_selection_validated_at",))
                logger.info(
                    "user=%s validated the contract selection of assessment=%s",
                    request.user.pk,
                    assessment.pk,
                    extra={"geiq_assessment": assessment.pk},
                )
            elif request.user.is_labor_inspector:
                assessment.grants_selection_validated_at = timezone.now()
                assessment.save(update_fields=("grants_selection_validated_at",))
                logger.info(
                    "user=%s validated the contract selection of assessment=%s",
                    request.user.pk,
                    assessment.pk,
                    extra={"geiq_assessment": assessment.pk},
                )
            next_url = back_url
        elif action == ContractsAction.UNVALIDATE:
            if not can_unvalidate:
                raise PermissionDenied
            if request.user.is_employer:
                assessment.contracts_selection_validated_at = None
                assessment.save(update_fields=("contracts_selection_validated_at",))
                logger.info(
                    "user=%s unvalidated the contract selection of assessment=%s",
                    request.user.pk,
                    assessment.pk,
                    extra={"geiq_assessment": assessment.pk},
                )
            elif request.user.is_labor_inspector:
                assessment.grants_selection_validated_at = None
                assessment.decision_validated_at = None
                assessment.save(update_fields=("decision_validated_at", "grants_selection_validated_at"))
                logger.info(
                    "user=%s unvalidated the contract selection of assessment=%s",
                    request.user.pk,
                    assessment.pk,
                    extra={"geiq_assessment": assessment.pk},
                )
            next_url = request.path
        else:
            # Unreachable code
            raise Http404

        return HttpResponseRedirect(next_url)

    if request.user.is_employer:
        stats = get_allowance_stats_for_geiq(assessment, for_assessment_details=False)
    elif request.user.is_labor_inspector:
        stats = get_allowance_stats_for_institution(assessment)
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
        "can_validate": can_validate,
        "can_unvalidate": can_unvalidate,
        "AssessmentContractDetailsTab": AssessmentContractDetailsTab,
        "ContractsAction": ContractsAction,
        "stats": stats,
    }
    return render(request, template_name, context)


class AssessmentContractDetailsTab(models.TextChoices):
    EMPLOYEE = "employee", "Informations salarié"
    CONTRACT = "contract", "Contrat"
    SUPPORT_AND_TRAINING = "support-and-training", "Accompagnement et formation"
    EXIT = "exit", "Sortie"


@check_user(lambda user: user.is_employer or user.is_labor_inspector)
def assessment_contracts_details(
    request, contract_pk, tab, template_name="geiq_assessments_views/assessment_contracts_details.html"
):
    try:
        details_tab = AssessmentContractDetailsTab(tab)
    except ValueError:
        raise Http404
    if request.user.is_employer:
        filter_kwargs = {"employee__assessment__companies": request.current_organization}
    elif request.user.is_labor_inspector:
        filter_kwargs = {
            "employee__assessment__institutions": request.current_organization,
            "employee__assessment__submitted_at__isnull": False,
        }
    else:
        raise Http404  # This should never happen thanks to check_user
    contract_qs = EmployeeContract.objects.filter(**filter_kwargs).select_related("employee__assessment__campaign")
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
    editable = False

    if request.user.is_employer:
        if not contract.employee.assessment.submitted_at:
            editable = not contract.employee.assessment.contracts_selection_validated_at
    elif request.user.is_labor_inspector:
        if not contract.employee.assessment.reviewed_at:
            editable = not contract.employee.assessment.grants_selection_validated_at
    context = {
        "back_url": back_url,
        "assessment": contract.employee.assessment,
        "editable": editable,
        "contract": contract,
        "matomo_custom_title": "Bilan d’exécution - page de detail d’un contrat",
        "AssessmentContractDetailsTab": AssessmentContractDetailsTab,
        "active_tab": details_tab,
    }
    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer or user.is_labor_inspector)
def assessment_contracts_toggle(
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
    from_list = bool(request.GET.get("from_list"))
    stats = None
    if from_list:
        if request.user.is_employer:
            stats = get_allowance_stats_for_geiq(assessment, for_assessment_details=False)
        elif request.user.is_labor_inspector:
            stats = get_allowance_stats_for_institution(assessment)
    context = {
        "assessment": assessment,
        "contract": contract,
        "from_list": from_list,
        "editable": True,
        "value": new_value,
        "stats": stats,
    }
    return render(request, template_name, context)


@require_safe
@check_user(lambda user: user.is_employer)
def assessment_kpi(request, pk, template_name="geiq_assessments_views/assessment_kpi.html"):
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    assessment = get_object_or_404(
        Assessment.objects.filter(contracts_synced_at__isnull=False)
        .filter(companies=request.current_organization.pk)
        .prefetch_related(
            Prefetch(
                "institution_links",
                queryset=AssessmentInstitutionLink.objects.select_related("institution"),
            ),
        ),
        pk=pk,
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
@check_user(lambda user: user.is_employer)
def assessment_result(request, pk, template_name="geiq_assessments_views/assessment_result.html"):
    if request.current_organization.kind != CompanyKind.GEIQ:
        raise Http404
    assessment = get_object_or_404(
        Assessment.objects.filter(contracts_synced_at__isnull=False)
        .filter(companies=request.current_organization.pk)
        .prefetch_related(
            Prefetch(
                "institution_links",
                queryset=AssessmentInstitutionLink.objects.select_related("institution"),
            ),
        ),
        pk=pk,
    )

    stats = EmployeeContract.objects.filter(employee__assessment=assessment, allowance_requested=True).aggregate(
        allowance_of_814_nb=Count("pk", filter=Q(employee__allowance_amount=814, allowance_granted=True)),
        allowance_of_814_submitted_nb=Count("pk", filter=Q(employee__allowance_amount=814)),
        allowance_of_1400_nb=Count("pk", filter=Q(employee__allowance_amount=1400, allowance_granted=True)),
        allowance_of_1400_submitted_nb=Count("pk", filter=Q(employee__allowance_amount=1400)),
        potential_allowance_amount=Sum("employee__allowance_amount", filter=Q(allowance_granted=True)),
    )

    context = {
        "assessment": assessment,
        "back_url": reverse("geiq_assessments_views:list_for_geiq"),
        "matomo_custom_title": "Bilan d’exécution - onglet des indicateurs clés",
        "AssessmentDetailsTab": AssessmentDetailsTab,
        "active_tab": AssessmentDetailsTab.RESULT,
        "abs_balance_amount": abs(assessment.granted_amount - assessment.advance_amount),
        "stats": stats,
    }
    return render(request, template_name, context)


@require_safe
@check_user(lambda user: user.is_labor_inspector)
def list_for_institution(request, template_name="geiq_assessments_views/list_for_institution.html"):
    if request.current_organization.kind not in (InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ):
        raise Http404
    assessments = (
        Assessment.objects.filter(institutions=request.current_organization)
        .select_related("campaign")
        .prefetch_related("institution_links__institution")
        .annotate(
            contracts_nb=Count("employees__contracts", filter=Q(employees__contracts__allowance_requested=True)),
        )
    )
    context = {
        "assessments": assessments,
    }
    return render(request, template_name, context)


class InstitutionAction(enum.StrEnum):
    REVIEW = "review"
    FIX = "fix"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


@check_user(lambda user: user.is_labor_inspector)
def assessment_details_for_institution(
    request, pk, template_name="geiq_assessments_views/assessment_details_for_institution.html"
):
    if request.current_organization.kind not in (InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ):
        raise Http404
    assessments = Assessment.objects.filter(institutions=request.current_organization).select_related(
        "campaign", "created_by", "submitted_by"
    )
    assessment = get_object_or_404(assessments, pk=pk)
    if request.method == "POST":
        try:
            action = InstitutionAction(request.POST.get("action"))
        except ValueError:
            raise Http404
        if action is InstitutionAction.REVIEW:
            if request.current_organization.kind == InstitutionKind.DREETS_GEIQ and assessment.dreets_reviewed_at:
                raise PermissionDenied
            now = timezone.now()
            if not assessment.reviewed_at:
                assessment.reviewed_at = now
                assessment.reviewed_by = request.user
                assessment.reviewed_by_institution = request.current_organization
                assessment.save(update_fields=("reviewed_at", "reviewed_by", "reviewed_by_institution"))
                logger.info(
                    "user=%s reviewed the assessment=%s",
                    request.user.pk,
                    assessment.pk,
                    extra={"geiq_assessment": assessment.pk},
                )
            elif request.current_organization.kind == InstitutionKind.DDETS_GEIQ:
                # DDETS trying to review an already reviewed assessment
                raise PermissionDenied
            if request.current_organization.kind == InstitutionKind.DREETS_GEIQ:
                if not assessment.dreets_reviewed_at:
                    assessment.dreets_reviewed_at = now
                    assessment.dreets_reviewed_by = request.user
                    assessment.save(update_fields=("dreets_reviewed_at", "dreets_reviewed_by"))
                    logger.info(
                        "user=%s dreets-reviewed the assessment=%s",
                        request.user.pk,
                        assessment.pk,
                        extra={"geiq_assessment": assessment.pk},
                    )
                else:
                    # DREETS trying to review an already dreets_reviewed assessment
                    raise PermissionDenied

        elif action is InstitutionAction.FIX:
            if request.current_organization.kind != InstitutionKind.DREETS_GEIQ or assessment.dreets_reviewed_at:
                raise PermissionDenied
            assessment.reviewed_at = None
            assessment.reviewed_by = None
            assessment.reviewed_by_institution = None
            assessment.save(update_fields=("reviewed_at", "reviewed_by", "reviewed_by_institution"))
            logger.info(
                "user=%s asked for a fix of assessment=%s",
                request.user.pk,
                assessment.pk,
                extra={"geiq_assessment": assessment.pk},
            )
        return HttpResponseRedirect(
            reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        )

    context = {
        "assessment": assessment,
        "back_url": reverse("geiq_assessments_views:list_for_institution"),
        "stats": (
            get_allowance_stats_for_institution(assessment, for_assessment_details=True)
            if assessment.submitted_at
            else None
        ),
        "InstitutionAction": InstitutionAction,
        "abs_balance_amount": abs(assessment.granted_amount - assessment.advance_amount),
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_labor_inspector)
def assessment_review(request, pk, template_name="geiq_assessments_views/assessment_review.html"):
    assessments = Assessment.objects.filter(institutions=request.current_organization)
    assessment = get_object_or_404(assessments, pk=pk)
    if not assessment.grants_selection_validated_at:
        raise Http404
    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
    )
    form = ReviewForm(instance=assessment, data=request.POST if request.method == "POST" else None)
    context = {
        "assessment": assessment,
        "form": form,
        "back_url": back_url,
    }
    if request.method == "POST" and form.is_valid():
        if assessment.reviewed_at:
            raise PermissionDenied
        form.save()
        assessment.decision_validated_at = timezone.now()
        assessment.save(update_fields=("decision_validated_at",))
        logger.info(
            "user=%s validated the decision of assessment=%s",
            request.user.pk,
            assessment.pk,
            extra={"geiq_assessment": assessment.pk},
        )
        return HttpResponseRedirect(back_url)
    # Avoid stats computation on successful POST
    context["stats"] = (
        EmployeeContract.objects.filter(employee__assessment=assessment)
        .filter(allowance_requested=True)
        .aggregate(
            allowance_of_814_nb=Count("pk", filter=Q(allowance_granted=True, employee__allowance_amount=814)),
            allowance_of_1400_nb=Count("pk", filter=Q(allowance_granted=True, employee__allowance_amount=1400)),
            refused_allowance_nb=Count("pk", filter=Q(allowance_granted=False)),
            potential_allowance_amount=Sum(
                Case(
                    When(allowance_granted=True, then="employee__allowance_amount"),
                    default=0,
                    output_field=models.IntegerField(),
                )
            ),
        )
    )

    return render(request, template_name, context)
