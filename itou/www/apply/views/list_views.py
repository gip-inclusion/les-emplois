from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.apply.forms import FilterJobApplicationsForm
from itou.job_applications.models import JobApplicationWorkflow


@login_required
@user_passes_test(lambda u: u.is_job_seeker, login_url="/", redirect_field_name=None)
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """

    job_applications_query = request.user.job_applications
    filters_form = FilterJobApplicationsForm()
    filters = request.GET

    if filters:
        filters_form = FilterJobApplicationsForm(data=filters)
        if filters_form.is_valid():
            job_applications_query = _add_filters_to_query(
                query=job_applications_query, data=filters_form.cleaned_data
            )
        filters = _humanize_filters(filters_form.cleaned_data)

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
        job_applications_query = prescriber_organization.jobapplication_set.all()
    else:
        job_applications_query = request.user.job_applications_sent.all()

    filters_form = FilterJobApplicationsForm()
    filters = request.GET
    if filters:
        filters_form = FilterJobApplicationsForm(data=filters)
        if filters_form.is_valid():
            job_applications_query = _add_filters_to_query(
                query=job_applications_query, data=filters_form.cleaned_data
            )
        filters = _humanize_filters(filters_form.cleaned_data)

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
    job_applications_query = siae.job_applications_received
    filters_form = FilterJobApplicationsForm()
    filters = request.GET

    if filters:
        filters_form = FilterJobApplicationsForm(data=filters)
        if filters_form.is_valid():
            job_applications_query = _add_filters_to_query(
                query=job_applications_query, data=filters_form.cleaned_data
            )
        filters = _humanize_filters(filters_form.cleaned_data)

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
        "filters": filters,
    }
    return render(request, template_name, context)


##########################################################################
######## Functions for internal-use only, not linked to a path. ##########
##########################################################################


def _add_filters_to_query(data, query):
    """
    Add filters coming from a form to a query.
    """

    # Active filters
    states = data.get("states")
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if states:
        query = query.filter(state__in=states)

    if start_date:
        query = query.filter(created_at__gte=start_date)

    if end_date:
        query = query.filter(created_at__lte=end_date)

    return query


def _humanize_filters(filters):
    """
    Return active filters to be displayed in a template.
    """
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    states = filters.get("states")
    active_filters = []

    if start_date:
        label = FilterJobApplicationsForm.base_fields.get("start_date").label
        active_filters.append([label, start_date])

    if end_date:
        label = FilterJobApplicationsForm.base_fields.get("end_date").label
        active_filters.append([label, end_date])

    if states:
        values = [str(JobApplicationWorkflow.states[state].title) for state in states]
        value = ", ".join(values)
        label = _("Statuts") if (len(values) > 1) else _("Statut")
        active_filters.append([label, value])

    return [{"label": f[0], "value": f[1]} for f in active_filters]
