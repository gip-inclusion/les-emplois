from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.text import slugify

from itou.job_applications.csv_export import generate_csv_export
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
    job_applications = job_applications.with_list_related_data()

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

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
        # Show all applications organization-wide + applications sent by the
        # current user for backward compatibility (in the past, a user could
        # create his prescriber's organization later on).
        job_applications = JobApplication.objects.filter(
            (Q(sender=request.user) & Q(sender_prescriber_organization__isnull=True))
            | Q(sender_prescriber_organization=prescriber_organization)
        )
    else:
        job_applications = request.user.job_applications_sent

    filters_form = PrescriberFilterJobApplicationsForm(job_applications, request.GET or None)
    filters = None

    job_applications = job_applications.with_list_related_data()

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)

    context = {"job_applications_page": job_applications_page, "filters_form": filters_form, "filters": filters}
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url="/", redirect_field_name=None)
def list_for_prescriber_exports(request, template_name="apply/list_of_available_exports.html"):
    """
    List of applications for a prescriber, sorted by month, displaying the count of applications per month
    with the possibiliy to download those applications as a CSV file.
    """
    if request.user.is_prescriber_with_org:
        prescriber_organization = get_current_org_or_404(request)
        # Show all applications organization-wide + applications sent by the
        # current user for backward compatibility (in the past, a user could
        # create his prescriber's organization later on).
        job_applications = JobApplication.objects.filter(
            (Q(sender=request.user) & Q(sender_prescriber_organization__isnull=True))
            | Q(sender_prescriber_organization=prescriber_organization)
        )
    else:
        job_applications = request.user.job_applications_sent

    job_applications_by_month = job_applications.with_monthly_counts()

    context = {"job_applications_by_month": job_applications_by_month, "export_for": "prescriber"}
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url="/", redirect_field_name=None)
def list_for_prescriber_exports_download(request, month_identifier):
    """
    List of applications for a prescriber for a given month identifier (YYYY-mm),
    exported as a CSV file with immediate download
    """
    if request.user.is_prescriber_with_org:
        prescriber_organization = get_current_org_or_404(request)
        # Show all applications organization-wide + applications sent by the
        # current user for backward compatibility (in the past, a user could
        # create his prescriber's organization later on).
        job_applications = JobApplication.objects.filter(
            (Q(sender=request.user) & Q(sender_prescriber_organization__isnull=True))
            | Q(sender_prescriber_organization=prescriber_organization)
        )
    else:
        job_applications = request.user.job_applications_sent

    year, month = month_identifier.split("-")
    job_applications = job_applications.created_on_given_year_and_month(year, month).with_list_related_data()

    filename = f"candidatures-{month_identifier}.csv"

    response = HttpResponse(content_type="text/csv", charset="utf-8")
    response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename)

    generate_csv_export(job_applications, response)

    return response


@login_required
def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """
    siae = get_current_siae_or_404(request)
    job_applications = siae.job_applications_received

    filters_form = SiaeFilterJobApplicationsForm(job_applications, request.GET or None)
    filters = None

    job_applications = job_applications.not_archived().with_list_related_data()

    if filters_form.is_valid():
        job_applications = job_applications.filter(*filters_form.get_qs_filters())
        filters = filters_form.humanize_filters()

    job_applications_page = pager(job_applications, request.GET.get("page"), items_per_page=10)

    context = {
        "siae": siae,
        "job_applications_page": job_applications_page,
        "filters_form": filters_form,
        "filters": filters,
    }
    return render(request, template_name, context)


@login_required
def list_for_siae_exports(request, template_name="apply/list_of_available_exports.html"):
    """
    List of applications for a SIAE, sorted by month, displaying the count of applications per month
    with the possibiliy to download those applications as a CSV file.
    """

    siae = get_current_siae_or_404(request)
    job_applications = siae.job_applications_received.not_archived()
    job_applications_by_month = job_applications.with_monthly_counts()

    context = {"job_applications_by_month": job_applications_by_month, "siae": siae, "export_for": "siae"}
    return render(request, template_name, context)


@login_required
def list_for_siae_exports_download(request, month_identifier):
    """
    List of applications for a SIAE for a given month identifier (YYYY-mm),
    exported as a CSV file with immediate download
    """
    year, month = month_identifier.split("-")
    siae = get_current_siae_or_404(request)
    job_applications = siae.job_applications_received.not_archived()
    job_applications = job_applications.created_on_given_year_and_month(year, month).with_list_related_data()
    filename = f"candidatures-{slugify(siae.display_name)}-{month_identifier}.csv"

    response = HttpResponse(content_type="text/csv", charset="utf-8")
    response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename)

    generate_csv_export(job_applications, response)

    return response
