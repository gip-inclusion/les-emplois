from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
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
from django.http import HttpResponse

def generate_csv_export_for_download(job_applications, filename="candidatures.csv"):
    """
    Converts a list of job application to CSV and return an HTTP response for download
    """
    response = HttpResponse(content_type="text/csv", charset="utf-16")
    response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename)

    generate_csv_export(job_applications, response)

    return response


def get_prescriber_job_application_list(request):
    """
    Returns the list of job_applications the current prescriber has
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
    return job_applications


def get_job_applications_by_month(job_applications):
    """
    Takes a list of job_applications, and returns a list of
    pairs (month, amount of job applications in this month)
    sorted by month
    """
    return (
        job_applications.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(c=Count("id"))
        .values("month", "c")
        .order_by("-month")
    )


def get_job_applications_for_export(job_applications, export_month):
    """
    Filters a list of job application in order only to return those created during the
    requested export_month (whose format is YYYY-mm)
    """
    year, month = export_month.split("-")
    job_applications = job_applications.filter(created_at__year=year, created_at__month=month)
    return job_applications.with_list_related_data()


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
    job_applications = get_prescriber_job_application_list(request)

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

    job_applications = get_prescriber_job_application_list(request)
    job_applications_by_month = get_job_applications_by_month(job_applications)

    context = {"job_applications_by_month": job_applications_by_month, "export_for": "prescriber"}
    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url="/", redirect_field_name=None)
def list_for_prescriber_exports_download(request, export_month):
    """
    List of applications for a prescriber for a given month (YYYY-mm), exported as a CSV file with immediate download
    """
    job_applications = get_prescriber_job_application_list(request)
    job_applications = get_job_applications_for_export(job_applications, export_month)

    return generate_csv_export_for_download(job_applications, f"candidatures-{export_month}.csv")


@login_required
def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """
    siae = get_current_siae_or_404(request)
    job_applications = siae.job_applications_received

    filters_form = SiaeFilterJobApplicationsForm(job_applications, request.GET or None)
    filters = None

    job_applications = job_applications.with_list_related_data()

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
    job_applications = siae.job_applications_received
    job_applications_by_month = get_job_applications_by_month(job_applications)

    context = {"job_applications_by_month": job_applications_by_month, "siae": siae, "export_for": "siae"}
    return render(request, template_name, context)


@login_required
def list_for_siae_exports_download(request, export_month):
    """
    List of applications for a SIAE for a given month (YYYY-mm), exported as a CSV file with immediate download
    """
    siae = get_current_siae_or_404(request)
    job_applications = siae.job_applications_received
    job_applications = get_job_applications_for_export(job_applications, export_month)

    return generate_csv_export_for_download(
        job_applications, f"candidatures-{slugify(siae.display_name)}-{export_month}.csv"
    )
