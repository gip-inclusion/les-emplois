from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.shortcuts import render

from itou.job_applications.models import JobApplication
from itou.utils.pagination import pager
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404
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
        "job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae"
    ).prefetch_related("selected_jobs__appellation")
    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)

    context = {"job_applications_page": job_applications_page, "filters_form": filters_form, "filters": filters}
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url="/", redirect_field_name=None)
def list_for_prescriber(request, template_name="apply/list_for_prescriber.html"):
    """
    List of applications for a prescriber.
    """

    if request.user.is_prescriber_with_org:
        prescriber_organization = get_current_org_or_404(request)
        # Show all applications organization-wide + applications sent by the current user
        # prior to the creation of the organization.
        job_applications = JobApplication.objects.filter(
            Q(sender=request.user) | Q(sender_prescriber_organization=prescriber_organization)
        )
    else:
        job_applications = request.user.job_applications_sent

    filters_form = PrescriberFilterJobApplicationsForm(job_applications, request.GET or None)
    filters = None

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications = job_applications.select_related(
        "job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae"
    ).prefetch_related("selected_jobs__appellation")

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)

    context = {"job_applications_page": job_applications_page, "filters_form": filters_form, "filters": filters}
    return render(request, template_name, context)


@login_required
def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """
    siae = get_current_siae_or_404(request)
    job_applications = siae.job_applications_received

    filters_form = SiaeFilterJobApplicationsForm(job_applications, request.GET or None)
    filters = None

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications = job_applications.select_related(
        "job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae"
    ).prefetch_related("selected_jobs__appellation")
    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)

    context = {
        "siae": siae,
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters": filters,
    }
    return render(request, template_name, context)
