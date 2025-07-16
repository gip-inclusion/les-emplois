import enum
import functools
from collections import defaultdict

from django.conf import settings
from django.db.models import Exists, F, OuterRef, Value
from django.db.models.functions import Concat, Lower
from django.http.response import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from itou.companies.enums import CompanyKind
from itou.eligibility.models import SelectedAdministrativeCriteria
from itou.job_applications.export import stream_xlsx_export
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.rdv_insertion.models import InvitationRequest
from itou.utils.auth import check_user
from itou.utils.ordering import OrderEnum
from itou.utils.pagination import pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    ArchivedChoices,
    BatchPostponeForm,
    CompanyFilterJobApplicationsForm,
    FilterJobApplicationsForm,
    JobApplicationInternalTransferForm,
    PrescriberFilterJobApplicationsForm,
)
from itou.www.apply.views.process_views import _get_geiq_eligibility_diagnosis
from itou.www.stats.utils import can_view_stats_ft


class JobApplicationsListKind(enum.Enum):
    RECEIVED = enum.auto()
    SENT = enum.auto()
    SENT_FOR_ME = enum.auto()

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


class JobApplicationsDisplayKind(enum.StrEnum):
    LIST = "list"
    TABLE = "table"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)

    # Ease the use in templates by avoiding the need to have access to JobApplicationsDisplayKind
    def is_list(self):
        return self is self.LIST

    def is_table(self):
        return self is self.TABLE


class JobApplicationOrder(OrderEnum):
    JOB_SEEKER_FULL_NAME_ASC = "job_seeker_full_name"
    JOB_SEEKER_FULL_NAME_DESC = "-job_seeker_full_name"
    CREATED_AT_ASC = "created_at"
    CREATED_AT_DESC = "-created_at"


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


@check_user(lambda u: u.is_job_seeker)
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """
    filters_form = FilterJobApplicationsForm(request.GET)
    job_applications = request.user.job_applications
    job_applications = job_applications.with_list_related_data()

    try:
        display_kind = JobApplicationsDisplayKind(request.GET.get("display"))
    except ValueError:
        display_kind = JobApplicationsDisplayKind.LIST

    if display_kind == JobApplicationsDisplayKind.LIST:
        job_applications = (
            job_applications.with_next_appointment_start_at()
            .with_upcoming_participations_count()
            .annotate(
                other_participations_count=F("upcoming_participations_count") - 1,  # Exclude the next appointment
            )
        )

    filters_counter = 0
    if filters_form.is_valid():
        job_applications = filters_form.filter(job_applications)
        filters_counter = filters_form.get_qs_filters_counter()

    try:
        order = JobApplicationOrder(request.GET.get("order"))
    except ValueError:
        order = JobApplicationOrder.CREATED_AT_DESC

    job_applications = job_applications.annotate(
        job_seeker_full_name=Concat(Lower("job_seeker__first_name"), Value(" "), Lower("job_seeker__last_name"))
    ).order_by(*order.order_by)

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=20)
    _add_pending_for_weeks(job_applications_page)

    # The candidate has obviously access to its personal info
    _add_user_can_view_personal_information(job_applications_page, lambda ja: True)

    context = {
        "job_applications_page": job_applications_page,
        "display_kind": display_kind,
        "order": order,
        "job_applications_list_kind": JobApplicationsListKind.SENT_FOR_ME,
        "JobApplicationsListKind": JobApplicationsListKind,
        "filters_form": filters_form,
        "filters_counter": filters_counter,
        "list_exports_url": None,
    }
    return render(
        request,
        "apply/includes/list_job_applications.html" if request.htmx else template_name,
        context,
    )


def annotate_title(base_title, archived_choice):
    match archived_choice:
        case ArchivedChoices.ARCHIVED:
            return f"{base_title} (archivées)"
        case ArchivedChoices.ALL:
            return f"{base_title} (toutes)"
        case ArchivedChoices.ACTIVE:
            return f"{base_title} (actives)"
        case _:
            raise ValueError(archived_choice)


@check_user(lambda u: u.is_prescriber or u.is_employer)
def list_prescriptions(request, template_name="apply/list_prescriptions.html"):
    """
    List of applications for a prescriber.
    """
    job_applications = JobApplication.objects.prescriptions_of(request.user, request.current_organization)

    filters_form = PrescriberFilterJobApplicationsForm(job_applications, request.GET, request=request)

    # Add related data giving the criteria for adding the necessary annotations
    job_applications = job_applications.with_list_related_data(criteria=filters_form.data.getlist("criteria", []))

    title = "Candidatures envoyées"
    filters_counter = 0
    if filters_form.is_valid():
        job_applications = filters_form.filter(job_applications)
        filters_counter = filters_form.get_qs_filters_counter()
        title = annotate_title(title, filters_form.cleaned_data["archived"])

    try:
        display_kind = JobApplicationsDisplayKind(request.GET.get("display"))
    except ValueError:
        display_kind = JobApplicationsDisplayKind.LIST

    try:
        order = JobApplicationOrder(request.GET.get("order"))
    except ValueError:
        order = JobApplicationOrder.CREATED_AT_DESC

    job_applications = job_applications.annotate(
        job_seeker_full_name=Concat(Lower("job_seeker__first_name"), Value(" "), Lower("job_seeker__last_name"))
    ).order_by(*order.order_by)

    if display_kind == JobApplicationsDisplayKind.LIST:
        job_applications = (
            job_applications.with_next_appointment_start_at()
            .with_upcoming_participations_count()
            .annotate(
                other_participations_count=F("upcoming_participations_count") - 1,  # Exclude the next appointment
            )
        )

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=20)
    _add_pending_for_weeks(job_applications_page)
    _add_user_can_view_personal_information(
        job_applications_page, functools.partial(can_view_personal_information, request)
    )
    _add_administrative_criteria(job_applications_page)

    context = {
        "title": title,
        "job_applications_page": job_applications_page,
        "display_kind": display_kind,
        "order": order,
        "job_applications_list_kind": JobApplicationsListKind.SENT,
        "JobApplicationsListKind": JobApplicationsListKind,
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


@check_user(lambda u: u.is_prescriber or u.is_employer)
def list_prescriptions_exports(request, template_name="apply/list_of_available_exports.html"):
    """
    List of applications for a prescriber, sorted by month, displaying the count of applications per month
    with the possibiliy to download those applications as a CSV file.
    """
    job_applications = JobApplication.objects.prescriptions_of(request.user, request.current_organization)
    total_job_applications = job_applications.count()
    job_applications_by_month = job_applications.with_monthly_counts()

    context = {
        "job_applications_by_month": job_applications_by_month,
        "total_job_applications": total_job_applications,
        "export_for": "prescriptions",
        "can_view_stats_ft": can_view_stats_ft(request),
        "back_url": get_safe_url(request, "back_url", reverse("dashboard:index")),
    }
    return render(request, template_name, context)


@check_user(lambda u: u.is_prescriber or u.is_employer)
def list_prescriptions_exports_download(request, month_identifier=None):
    """
    List of applications for a prescriber for a given month identifier (YYYY-mm),
    exported as a CSV file with immediate download
    """
    job_applications = JobApplication.objects.prescriptions_of(
        request.user, request.current_organization
    ).with_list_related_data()
    filename = "candidatures"
    if month_identifier:
        year, month = month_identifier.split("-")
        filename = f"{filename}-{month_identifier}"
        job_applications = job_applications.created_on_given_year_and_month(year, month)

    return stream_xlsx_export(job_applications, filename, request=request)


def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """
    company = get_current_company_or_404(request)
    job_applications = company.job_applications_received
    pending_states_job_applications_count = job_applications.filter(
        state__in=JobApplicationWorkflow.PENDING_STATES
    ).count()

    filters_form = CompanyFilterJobApplicationsForm(job_applications, company, request.GET)

    # Add related data giving the criteria for adding the necessary annotations
    job_applications = job_applications.with_list_related_data(filters_form.data.getlist("criteria", []))

    title = "Candidatures reçues"
    filters_counter = 0
    if filters_form.is_valid():
        job_applications = filters_form.filter(job_applications)
        filters_counter = filters_form.get_qs_filters_counter()
        title = annotate_title(title, filters_form.cleaned_data["archived"])

    try:
        display_kind = JobApplicationsDisplayKind(request.GET.get("display"))
    except ValueError:
        display_kind = JobApplicationsDisplayKind.TABLE

    if display_kind == JobApplicationsDisplayKind.LIST:
        job_applications = (
            job_applications.with_next_appointment_start_at()
            .with_upcoming_participations_count()
            .annotate(
                has_pending_rdv_insertion_invitation_request=Exists(
                    InvitationRequest.objects.filter(
                        job_seeker=OuterRef("job_seeker"),
                        company=OuterRef("to_company"),
                        created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
                    )
                ),
                other_participations_count=F("upcoming_participations_count") - 1,  # Exclude the next appointment
            )
        )

    try:
        order = JobApplicationOrder(request.GET.get("order"))
    except ValueError:
        order = JobApplicationOrder.CREATED_AT_DESC

    job_applications = job_applications.annotate(
        job_seeker_full_name=Concat(Lower("job_seeker__first_name"), Value(" "), Lower("job_seeker__last_name"))
    ).order_by(*order.order_by)

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=20)
    _add_pending_for_weeks(job_applications_page)

    # SIAE members have access to personal info
    _add_user_can_view_personal_information(job_applications_page, lambda ja: True)

    iae_company = company.kind in CompanyKind.siae_kinds()
    if iae_company:
        _add_administrative_criteria(job_applications_page)

    context = {
        "title": title,
        "siae": company,
        "job_applications_page": job_applications_page,
        "display_kind": display_kind,
        "order": order,
        "job_applications_list_kind": JobApplicationsListKind.RECEIVED,
        "JobApplicationsListKind": JobApplicationsListKind,
        "filters_form": filters_form,
        "filters_counter": filters_counter,
        "pending_states_job_applications_count": pending_states_job_applications_count,
        "list_exports_url": reverse("apply:list_for_siae_exports"),
        "back_url": reverse("dashboard:index"),
        "can_apply": company.kind in CompanyKind.siae_kinds() + [CompanyKind.GEIQ],
        "mon_recap_banner_departments": settings.MON_RECAP_BANNER_DEPARTMENTS,
    }
    return render(
        request,
        "apply/includes/list_job_applications.html" if request.htmx else template_name,
        context,
    )


def list_for_siae_exports(request, template_name="apply/list_of_available_exports.html"):
    """
    List of applications for a SIAE, sorted by month, displaying the count of applications per month
    with the possibiliy to download those applications as a CSV file.
    """

    company = get_current_company_or_404(request)
    job_applications = company.job_applications_received
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


def list_for_siae_exports_download(request, month_identifier=None):
    """
    List of applications for a SIAE for a given month identifier (YYYY-mm),
    exported as a CSV file with immediate download
    """
    company = get_current_company_or_404(request)
    job_applications = company.job_applications_received.with_list_related_data()
    filename = f"candidatures-{slugify(company.display_name)}"
    if month_identifier:
        year, month = month_identifier.split("-")
        filename = f"{filename}-{month_identifier}"
        job_applications = job_applications.created_on_given_year_and_month(year, month)

    return stream_xlsx_export(job_applications, filename, request=request)


@check_user(lambda user: user.is_employer)
def list_for_siae_actions(request):
    company = get_current_company_or_404(request)
    selected_job_applications = list(
        company.job_applications_received.filter(pk__in=request.GET.getlist("selected-application"))
    )
    selected_nb = len(selected_job_applications)
    if selected_nb != len(request.GET.getlist("selected-application")):
        # Something is fishy, let's force a refresh to reorder the universe
        response = HttpResponse()
        response["HX-Refresh"] = "true"
        return response
    can_archive = any(job_application.can_be_archived for job_application in selected_job_applications)
    can_unarchive = any(job_application.archived_at is not None for job_application in selected_job_applications)
    can_postpone = all(job_application.postpone.is_available() for job_application in selected_job_applications)
    can_process = all(job_application.process.is_available() for job_application in selected_job_applications)
    can_refuse = all(job_application.refuse.is_available() for job_application in selected_job_applications)
    enable_transfer = len(request.organizations) > 1
    can_transfer = enable_transfer and (
        all(job_application.transfer.is_available() for job_application in selected_job_applications)
    )
    cannot_accept_reason = None
    if len(selected_job_applications) != 1:
        cannot_accept_reason = "Une seule candidature doit être séléctionnée pour être acceptée."
    elif not selected_job_applications[0].accept.is_available():
        cannot_accept_reason = "Cette candidature est déjà acceptée."
    can_accept = cannot_accept_reason is None
    if can_accept and company.kind == CompanyKind.GEIQ:
        selected_job_applications[0].geiq_eligibility_diagnosis = _get_geiq_eligibility_diagnosis(
            selected_job_applications[0], only_prescriber=False
        )
    context = {
        "display_batch_actions": bool(selected_job_applications),
        "selected_nb": len(selected_job_applications),
        "selected_application_ids": [job_app.pk for job_app in selected_job_applications],
        "can_accept": can_accept,
        "cannot_accept_reason": cannot_accept_reason,
        "can_archive": can_archive,
        "can_unarchive": can_unarchive,
        "can_process": can_process,
        "can_postpone": can_postpone,
        "can_refuse": can_refuse,
        "can_transfer": can_transfer,
        "enable_transfer": enable_transfer,
        "other_actions_count": sum([can_process, can_postpone, can_archive, can_transfer]),
        "transfer_form": JobApplicationInternalTransferForm(request, job_app_count=selected_nb),
        "postpone_form": BatchPostponeForm(
            job_seeker_nb=len(set(job_application.job_seeker_id for job_application in selected_job_applications))
        )
        if can_postpone
        else None,
        "list_url": get_safe_url(request, "list_url", fallback_url=reverse("apply:list_for_siae")),
        "acceptable_job_application": selected_job_applications[0] if can_accept else None,
    }
    response = render(
        request,
        "apply/includes/siae_batch_actions.html",
        context,
    )
    return response
