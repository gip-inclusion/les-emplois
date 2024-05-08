from collections import defaultdict

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.text import slugify

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.eligibility.models import SelectedAdministrativeCriteria
from itou.job_applications.export import stream_xlsx_export
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.pagination import pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.prescriber import get_all_available_job_applications_as_prescriber
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    CompanyFilterJobApplicationsForm,
    FilterJobApplicationsForm,
    PrescriberFilterJobApplicationsForm,
)
from itou.www.stats.utils import can_view_stats_pe


def _add_user_can_view_personal_information(job_applications, can_view):
    for job_application in job_applications:
        job_application.user_can_view_personal_information = can_view(job_application.job_seeker)


def _add_pending_for_weeks(job_applications):
    SECONDS_IN_WEEK = 7 * 24 * 60 * 60
    for job_app in job_applications:
        pending_for_weeks = None
        if job_app.state in JobApplicationWorkflow.PENDING_STATES:
            pending_for_seconds = (timezone.now() - job_app.last_change).total_seconds()
            pending_for_weeks = int(pending_for_seconds // SECONDS_IN_WEEK)
        job_app.pending_for_weeks = pending_for_weeks


def _add_administrative_criteria(job_applications):
    diagnoses_ids = tuple(
        job_application.jobseeker_eligibility_diagnosis
        for job_application in job_applications
        if job_application.jobseeker_eligibility_diagnosis is not None
    )

    diagnosis_criteria = defaultdict(list)
    for selected_criteria in (
        SelectedAdministrativeCriteria.objects.filter(eligibility_diagnosis__in=diagnoses_ids)
        .select_related("administrative_criteria")
        .order_by("administrative_criteria__level", "administrative_criteria__name")
    ):
        diagnosis_criteria[selected_criteria.eligibility_diagnosis_id].append(
            selected_criteria.administrative_criteria
        )

    for job_application in job_applications:
        ja_criteria = diagnosis_criteria[job_application.jobseeker_eligibility_diagnosis]
        if len(ja_criteria) > 4:
            # Only show the 3 first
            extra_nb = len(ja_criteria) - 3
            ja_criteria = ja_criteria[:3]
        else:
            extra_nb = 0
        job_application.preloaded_administrative_criteria = ja_criteria
        job_application.preloaded_administrative_criteria_extra_nb = extra_nb


@login_required
@user_passes_test(lambda u: u.is_job_seeker, login_url=reverse_lazy("search:employers_home"), redirect_field_name=None)
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """
    filters_form = FilterJobApplicationsForm(request.GET or None)
    job_applications = request.user.job_applications
    job_applications = job_applications.with_list_related_data()

    filters_counter = 0
    if filters_form.is_valid():
        job_applications = filters_form.filter(job_applications)
        filters_counter = filters_form.get_qs_filters_counter()

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)
    _add_pending_for_weeks(job_applications_page)

    # The candidate has obviously access to its personal info
    _add_user_can_view_personal_information(job_applications_page, lambda ja: True)

    context = {
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters_counter": filters_counter,
        "list_exports_url": None,
    }
    return render(
        request,
        "apply/includes/list_job_applications.html" if request.htmx else template_name,
        context,
    )


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url=reverse_lazy("search:employers_home"), redirect_field_name=None)
def list_prescriptions(request, template_name="apply/list_prescriptions.html"):
    """
    List of applications for a prescriber.
    """
    job_applications = get_all_available_job_applications_as_prescriber(request)

    filters_form = PrescriberFilterJobApplicationsForm(job_applications, request.GET or None)

    # Add related data giving the criteria for adding the necessary annotations
    job_applications = job_applications.with_list_related_data(criteria=filters_form.data.getlist("criteria", []))

    filters_counter = 0
    if filters_form.is_valid():
        job_applications = filters_form.filter(job_applications)
        filters_counter = filters_form.get_qs_filters_counter()

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)
    _add_pending_for_weeks(job_applications_page)
    _add_user_can_view_personal_information(job_applications_page, request.user.can_view_personal_information)
    _add_administrative_criteria(job_applications_page)

    context = {
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters_counter": filters_counter,
        "list_exports_url": reverse("apply:list_prescriptions_exports"),
        "back_url": reverse("dashboard:index"),
    }
    return render(
        request,
        "apply/includes/list_job_applications.html" if request.htmx else template_name,
        context,
    )


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url=reverse_lazy("search:employers_home"), redirect_field_name=None)
def list_prescriptions_exports(request, template_name="apply/list_of_available_exports.html"):
    """
    List of applications for a prescriber, sorted by month, displaying the count of applications per month
    with the possibiliy to download those applications as a CSV file.
    """
    job_applications = get_all_available_job_applications_as_prescriber(request)
    total_job_applications = job_applications.count()
    job_applications_by_month = job_applications.with_monthly_counts()

    context = {
        "job_applications_by_month": job_applications_by_month,
        "total_job_applications": total_job_applications,
        "export_for": "prescriptions",
        "can_view_stats_pe": can_view_stats_pe(request),
        "back_url": get_safe_url(request, "back_url", reverse("dashboard:index")),
    }
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url=reverse_lazy("search:employers_home"), redirect_field_name=None)
def list_prescriptions_exports_download(request, month_identifier=None):
    """
    List of applications for a prescriber for a given month identifier (YYYY-mm),
    exported as a CSV file with immediate download
    """
    job_applications = get_all_available_job_applications_as_prescriber(request).with_list_related_data()
    filename = "candidatures"
    if month_identifier:
        year, month = month_identifier.split("-")
        filename = f"{filename}-{month_identifier}"
        job_applications = job_applications.created_on_given_year_and_month(year, month)

    return stream_xlsx_export(job_applications, filename)


@login_required
def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """
    company = get_current_company_or_404(request)
    job_applications = company.job_applications_received
    pending_states_job_applications_count = job_applications.filter(
        state__in=JobApplicationWorkflow.PENDING_STATES
    ).count()

    filters_form = CompanyFilterJobApplicationsForm(job_applications, company, request.GET or None)

    # Add related data giving the criteria for adding the necessary annotations
    job_applications = job_applications.not_archived().with_list_related_data(
        filters_form.data.getlist("criteria", [])
    )

    filters_counter = 0
    if filters_form.is_valid():
        job_applications = filters_form.filter(job_applications)
        filters_counter = filters_form.get_qs_filters_counter()

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)
    _add_pending_for_weeks(job_applications_page)

    # SIAE members have access to personal info
    _add_user_can_view_personal_information(job_applications_page, lambda ja: True)

    if company.kind in SIAE_WITH_CONVENTION_KINDS:
        _add_administrative_criteria(job_applications_page)

    context = {
        "siae": company,
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters_counter": filters_counter,
        "pending_states_job_applications_count": pending_states_job_applications_count,
        "list_exports_url": reverse("apply:list_for_siae_exports"),
        "back_url": reverse("dashboard:index"),
    }
    return render(
        request,
        "apply/includes/list_job_applications.html" if request.htmx else template_name,
        context,
    )


@login_required
def list_for_siae_exports(request, template_name="apply/list_of_available_exports.html"):
    """
    List of applications for a SIAE, sorted by month, displaying the count of applications per month
    with the possibiliy to download those applications as a CSV file.
    """

    company = get_current_company_or_404(request)
    job_applications = company.job_applications_received.not_archived()
    total_job_applications = job_applications.count()
    job_applications_by_month = job_applications.with_monthly_counts()

    context = {
        "job_applications_by_month": job_applications_by_month,
        "total_job_applications": total_job_applications,
        "siae": company,
        "export_for": "siae",
        "back_url": get_safe_url(request, "back_url", reverse("dashboard:index")),
    }
    return render(request, template_name, context)


@login_required
def list_for_siae_exports_download(request, month_identifier=None):
    """
    List of applications for a SIAE for a given month identifier (YYYY-mm),
    exported as a CSV file with immediate download
    """
    company = get_current_company_or_404(request)
    job_applications = company.job_applications_received.not_archived().with_list_related_data()
    filename = f"candidatures-{slugify(company.display_name)}"
    if month_identifier:
        year, month = month_identifier.split("-")
        filename = f"{filename}-{month_identifier}"
        job_applications = job_applications.created_on_given_year_and_month(year, month)

    return stream_xlsx_export(job_applications, filename)
