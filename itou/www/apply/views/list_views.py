from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, render

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.apply.forms import (
    FilterJobApplicationsForm,
    PrescriberFilterJobApplicationsForm,
    SiaeFilterJobApplicationsForm,
)


@login_required
@user_passes_test(lambda u: u.is_job_seeker, login_url="/", redirect_field_name=None)
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """
    filters_form = FilterJobApplicationsForm(request.GET or None)
    filters = None
    job_applications = request.user.job_applications

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications = job_applications.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("selected_jobs__appellation")
    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters": filters,
    }
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url="/", redirect_field_name=None)
def list_for_prescriber(request, template_name="apply/list_for_prescriber.html"):
    """
    List of applications for a prescriber.
    """

    prescriber_organization = None
    pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
    if pk:
        queryset = PrescriberOrganization.objects.member_required(request.user)
        prescriber_organization = get_object_or_404(queryset, pk=pk)

    if prescriber_organization:
        # Show all applications organization-wide.
        job_applications = prescriber_organization.jobapplication_set
    else:
        job_applications = request.user.job_applications_sent

    filters_form = PrescriberFilterJobApplicationsForm(
        job_applications, request.GET or None
    )
    filters = None

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications = job_applications.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("selected_jobs__appellation")

    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters": filters,
    }
    return render(request, template_name, context)


@login_required
def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """

    pk = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.active_objects.member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)
    job_applications = siae.job_applications_received

    filters_form = SiaeFilterJobApplicationsForm(job_applications, request.GET or None)
    filters = None

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications = job_applications.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("selected_jobs__appellation")
    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {
        "siae": siae,
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters": filters,
    }
    return render(request, template_name, context)
