from datetime import datetime, time

from django.utils import timezone
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.apply.forms import FilterJobApplicationsForm


@login_required
@user_passes_test(lambda u: u.is_job_seeker, login_url="/", redirect_field_name=None)
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """

    job_applications = request.user.job_applications.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("selected_jobs__appellation")
    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {"job_applications_page": job_applications_page}
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
        job_applications = prescriber_organization.jobapplication_set.all()
    else:
        job_applications = request.user.job_applications_sent.all()

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

    context = {"job_applications_page": job_applications_page}
    return render(request, template_name, context)


@login_required
def list_for_siae(request, template_name="apply/list_for_siae.html"):
    """
    List of applications for an SIAE.
    """

    pk = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.active_objects.member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)
    job_applications_query = siae.job_applications_received
    filters_form = FilterJobApplicationsForm()
    filters = request.GET

    if filters:
        filters_form = FilterJobApplicationsForm(data=filters)
        job_applications_query = _add_filters_to_query(
            query=job_applications_query, form=filters_form
        )

    job_applications = job_applications_query.select_related(
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
    }
    return render(request, template_name, context)


##########################################################################
######## Functions for internal-use only, not linked to a path. ##########
##########################################################################


def _add_filters_to_query(query, form):
    """
    Add filters coming from a form to a query.
    Input:
        query: Django QuerySet type
        form: Django Form type
    Output:
        Django QuerySet type
    """
    if form.is_valid():
        data = form.cleaned_data

        # Active filters
        states = data.get("states")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        if states:
            query = query.filter(state__in=states)

        if start_date or end_date:
            start_date, end_date = _process_dates(start_date, end_date)
            query = query.filter(created_at__range=[start_date, end_date])

    return query


def _process_dates(start_date: datetime, end_date: datetime):
    """
    When a start_date and an end_date do not include time values,
    consider that it means "the whole day".
    Therefore, start_date time should be 0 am and end_date time should be 23.59 pm.
    """
    start_date = datetime.combine(start_date, time())
    start_date = timezone.make_aware(start_date)

    end_date = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    end_date = timezone.make_aware(end_date)

    return start_date, end_date
