from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render

from itou.siaes.models import Siae
from itou.utils.pagination import pager


@login_required
@user_passes_test(lambda u: u.is_job_seeker, login_url="/", redirect_field_name=None)
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """

    job_applications = request.user.job_applications_sent.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("jobs")
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

    job_applications = request.user.job_applications_sent.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("jobs")
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

    job_applications = siae.job_applications_received.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    ).prefetch_related("jobs")
    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {"siae": siae, "job_applications_page": job_applications_page}
    return render(request, template_name, context)
