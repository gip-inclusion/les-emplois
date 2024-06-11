import datetime
import enum
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import default_storage
from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery, Sum
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from itou.common_apps.address.departments import REGIONS
from itou.files.models import File
from itou.geiq.models import (
    Employee,
    EmployeeContract,
    EmployeePrequalification,
    ImplementationAssessment,
    ReviewState,
)
from itou.geiq.sync import sync_employee_and_contracts
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.utils.apis import geiq_label
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url

from .forms import AssessmentReviewForm, AssessmentSubmissionForm


logger = logging.getLogger(__name__)


ASSESSMENT_INFO_MATOMO_TITLE = "Information d’un bilan d’exécution"


class InfoType(enum.StrEnum):
    PERSONAL_INFORMATION = "personal-information"
    JOB_APPLICATION = "job-application"
    SUPPORT = "support"
    CONTRACT = "contract"
    EXIT = "exit"

    # Otherwise Django will detect InfoType as callable and access to individual values does not work
    do_not_call_in_templates = enum.nonmember(True)


def _get_assessments_for_labor_inspector(request):
    reviewable_departments = []
    for institution in request.organizations:
        if institution.kind in (InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ):
            if institution.kind == InstitutionKind.DDETS_GEIQ:
                reviewable_departments.append(institution.department)
            else:
                reviewable_departments.extend(REGIONS[institution.region])
    return ImplementationAssessment.objects.filter(company__department__in=reviewable_departments).select_related(
        "campaign", "company"
    )


@login_required
@user_passes_test(
    lambda user: user.is_active and (user.is_employer or user.is_labor_inspector), redirect_field_name=None
)
def assessment_info(request, assessment_pk):
    if request.user.is_employer:
        return _assessment_info_for_employer(request, assessment_pk)
    if request.user.is_labor_inspector:
        return _assessment_info_for_labor_inspector(request, assessment_pk)


def _assessment_info_for_employer(request, assessment_pk, template_name="geiq/assessment_info_for_employer.html"):
    assessments = ImplementationAssessment.objects.filter(
        company_id__in={org.pk for org in request.organizations}
    ).select_related("campaign", "company")
    assessment = get_object_or_404(assessments, pk=assessment_pk)

    submission_form = AssessmentSubmissionForm(data=request.POST or None, files=request.FILES or None)
    if request.method == "POST" and submission_form.is_valid():
        if assessment.submitted_at:
            submission_form.add_error(None, "Dossier déjà transmis")
        elif not assessment.last_synced_at:
            submission_form.add_error(
                None,
                (
                    "Aucune donnée salariés synchronisée. "
                    "Veuillez synchroniser et vérifier les données avant d’envoyer le bilan."
                ),
            )
        else:
            report_file = submission_form.cleaned_data["activity_report_file"]
            report_key = default_storage.save(f"geiq_activity_report/{report_file.name}", report_file)
            assessment.activity_report_file = File.objects.create(key=report_key)
            assessment.submitted_at = timezone.now()
            assessment.submitted_by = request.user
            assessment.save(update_fields={"activity_report_file", "submitted_at", "submitted_by"})

    if assessment.submitted_at:
        submission_form.fields["up_to_date_information"].widget.attrs.update(
            {"disabled": "disabled", "checked": "checked"}
        )
    context = {
        "InfoType": InfoType,
        "assessment": assessment,
        "submission_form": submission_form,
        "ReviewState": ReviewState,
        "back_url": reverse("dashboard:index"),
        "matomo_custom_title": ASSESSMENT_INFO_MATOMO_TITLE,
    }
    return render(request, template_name, context)


def _assessment_info_for_labor_inspector(
    request, assessment_pk, template_name="geiq/assessment_info_for_labor_inspector.html"
):
    assessment = get_object_or_404(_get_assessments_for_labor_inspector(request), pk=assessment_pk)

    context = {
        "matomo_custom_title": ASSESSMENT_INFO_MATOMO_TITLE,
        "InfoType": InfoType,
        "assessment": assessment,
        "ReviewState": ReviewState,
        "back_url": reverse("geiq:geiq_list", kwargs={"institution_pk": request.current_organization.pk}),
    }
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda user: user.is_active and user.is_labor_inspector, redirect_field_name=None)
def assessment_review(request, assessment_pk, template_name="geiq/assessment_review.html"):
    assessment = get_object_or_404(_get_assessments_for_labor_inspector(request), pk=assessment_pk)
    back_url = reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk})
    form = AssessmentReviewForm(data=request.POST or None, instance=assessment)
    if request.method == "POST" and form.is_valid():
        form.instance.reviewed_at = timezone.now()
        form.instance.reviewed_by = request.user
        form.instance.review_institution = request.current_organization
        form.save()
        return HttpResponseRedirect(back_url)
    context = {
        "InfoType": InfoType,
        "assessment": assessment,
        "form": form,
        "ReviewState": ReviewState,
        "back_url": back_url,
        "matomo_custom_title": "Saisie d’un avis sur un bilan d’exécution par une institution",
    }
    return render(request, template_name, context)


@login_required
@user_passes_test(
    lambda user: user.is_active and (user.is_employer or user.is_labor_inspector), redirect_field_name=None
)
def employee_list(request, assessment_pk, info_type):
    try:
        info_type = InfoType(info_type)
    except ValueError:
        raise Http404("Type de donnée inconnu")
    if request.user.is_labor_inspector:
        assessment = get_object_or_404(_get_assessments_for_labor_inspector(request), pk=assessment_pk)
    else:
        assessments = ImplementationAssessment.objects.filter(
            company_id__in={org.pk for org in request.organizations}
        ).select_related("campaign", "company")
        assessment = get_object_or_404(assessments, pk=assessment_pk)
    if request.POST and not assessment.submitted_at:
        try:
            _lock_assessment_and_sync(assessment)
        except ImproperlyConfigured:
            messages.error(request, "Synchronisation impossible avec Label: configuration incomplète")
        except geiq_label.LabelAPIError:
            logger.warning("Error while syncing Label data for assessement=%s", assessment)
            messages.error(request, "Erreur lors de la synchronisation avec Label.")

    match info_type:
        case InfoType.PERSONAL_INFORMATION:
            queryset = Employee.objects.filter(assessment=assessment).order_by("last_name", "first_name")
            template_name = "geiq/employee_personal_information_list.html"
        case InfoType.JOB_APPLICATION:
            queryset = Employee.objects.filter(assessment=assessment).order_by("last_name", "first_name")
            template_name = "geiq/employee_job_application_list.html"
        case InfoType.SUPPORT:
            queryset = (
                EmployeeContract.objects.filter(employee__assessment=assessment)
                .order_by("employee__last_name", "employee__first_name")
                .select_related("employee")
                .prefetch_related(
                    Prefetch(
                        "employee__prequalifications",
                        # order_by to provide a pre-sorted list to display_prior_actions method
                        queryset=EmployeePrequalification.objects.order_by("-end_at"),
                    )
                )
            )
            template_name = "geiq/employee_support_list.html"
        case InfoType.CONTRACT:
            queryset = (
                EmployeeContract.objects.filter(employee__assessment=assessment)
                .order_by("employee__last_name", "employee__first_name")
                .select_related("employee")
            )
            template_name = "geiq/employee_contract_list.html"
        case InfoType.EXIT:
            queryset = (
                EmployeeContract.objects.filter(employee__assessment=assessment)
                .order_by("employee__last_name", "employee__first_name")
                .select_related("employee")
            )
            template_name = "geiq/employee_exit_list.html"

    stats = Employee.objects.filter(assessment=assessment).aggregate(
        accompanied_nb=Count("pk"),
        accompanied_more_than_90_days_nb=Count("pk", filter=Q(support_days_nb__gte=90)),
        eligible_for_aid_employee_nb=Count("pk", filter=~Q(allowance_amount=0)),
        potential_aid_of_814_nb=Count("pk", filter=Q(allowance_amount=814)),
        potential_aid_of_1400_nb=Count("pk", filter=Q(allowance_amount=1400)),
        potential_aid_amount=Sum("allowance_amount"),
    )

    context = {
        "active_tab": info_type,
        "data_page": pager(queryset, request.GET.get("page"), items_per_page=50),
        "InfoType": InfoType,
        "assessment": assessment,
        "back_url": get_safe_url(
            request, "back_url", fallback_url=reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk})
        ),
        "matomo_custom_title": f"Liste des salariés d’un bilan d’exécution - onglet: {info_type}",
        **stats,
    }
    return render(request, template_name, context)


def _lock_assessment_and_sync(assessment):
    # Take lock
    lock_assessment = get_object_or_404(ImplementationAssessment.objects.filter(pk=assessment.pk).select_for_update())
    if lock_assessment.last_synced_at and lock_assessment.last_synced_at > timezone.now() + datetime.timedelta(
        minutes=1
    ):
        return False
    # Use the provided assessment as it will update last_synced_at field
    sync_employee_and_contracts(assessment)
    return True


@login_required
@require_POST
@user_passes_test(lambda user: user.is_active and user.is_employer, redirect_field_name=None)
def label_sync(request, assessment_pk):
    assessment = get_object_or_404(
        ImplementationAssessment.objects.filter(
            company_id__in={org.pk for org in request.organizations},
            submitted_at__isnull=True,  # You cannot sync data anymore after submission
        ),
        pk=assessment_pk,
    )
    _lock_assessment_and_sync(assessment)

    context = {
        "assessment": assessment,
        "allow_sync": True,
    }
    return render(request, "geiq/includes/last_synced_at.html", context)


@login_required
@require_safe
@user_passes_test(
    lambda user: user.is_active and (user.is_employer or user.is_labor_inspector), redirect_field_name=None
)
def employee_details(request, employee_pk):
    if request.user.is_labor_inspector:
        assessments = _get_assessments_for_labor_inspector(request)
        employees = Employee.objects.filter(assessment__in=assessments).select_related("assessment__campaign")
    else:
        employees = Employee.objects.filter(
            assessment__company_id__in={org.pk for org in request.organizations},
        ).select_related("assessment__campaign")
    employee = get_object_or_404(employees, pk=employee_pk)
    context = {
        "back_url": get_safe_url(
            request,
            "back_url",
            fallback_url=reverse(
                "geiq:employee_list",
                kwargs={"assessment_pk": employee.assessment.pk, "info_type": InfoType.PERSONAL_INFORMATION},
            ),
        ),
        "employee": employee,
        "contracts": employee.contracts.order_by("start_at"),
        "prequalifications": employee.prequalifications.order_by("start_at"),
        "matomo_custom_title": "Détail d’un salarié d’un bilan d’exécution",
    }
    return render(request, "geiq/employee_details.html", context)


@login_required
@user_passes_test(lambda user: user.is_active and user.is_labor_inspector, redirect_field_name=None)
def geiq_list(request, institution_pk, year=None, template_name="geiq/geiq_list.html"):
    institution = get_object_or_404(
        Institution.objects.filter(
            kind__in=(InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ),
            pk__in={org.pk for org in request.organizations},
        ),
        pk=institution_pk,
    )
    if institution.kind == InstitutionKind.DDETS_GEIQ:
        reviewable_departments = [institution.department]
    else:
        reviewable_departments = REGIONS[institution.region]

    max_year_subquery = (
        ImplementationAssessment.objects.filter(company_id=OuterRef("company_id"))
        .order_by("-campaign__year")
        .values("campaign__year")[:1]
    )
    assessments = (
        ImplementationAssessment.objects.filter(company__department__in=reviewable_departments)
        .annotate(max_year=Subquery(max_year_subquery))
        .filter(campaign__year=F("max_year"))
        .select_related("company", "campaign")
        .annotate(eligible_employees_nb=Count("employees", filter=Q(employees__allowance_amount__gt=0)))
        .order_by("company__name")
    )

    context = {
        "assessments": assessments,
        "back_url": reverse("dashboard:index"),
        "ReviewState": ReviewState,
        "matomo_custom_title": "Liste des GEIQ ayant un bilan d’exécution",
    }
    return render(request, template_name, context)


@require_safe
@login_required
@user_passes_test(
    lambda user: user.is_active and (user.is_employer or user.is_labor_inspector), redirect_field_name=None
)
def assessment_report(request, assessment_pk):
    if request.user.is_labor_inspector:
        assessments = (
            _get_assessments_for_labor_inspector(request)
            .filter(activity_report_file__isnull=False)
            .select_related(None)
        )
    else:
        assessments = ImplementationAssessment.objects.filter(company_id__in={org.pk for org in request.organizations})
    assessment = get_object_or_404(assessments, pk=assessment_pk)
    return HttpResponseRedirect(default_storage.url(assessment.activity_report_file_id))
