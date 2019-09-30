import urllib.parse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import ugettext as _

from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.apply.forms import (
    JobApplicationForm,
    JobApplicationAnswerForm,
    JobApplicationProcessForm,
)


@login_required
def submit_for_job_seeker(
    request, siret, template_name="apply/submit_for_job_seeker.html"
):
    """
    Submit a job application as a job seeker.
    """

    prev_url = request.META.get("HTTP_REFERER", "/")

    if not request.user.is_job_seeker:
        messages.error(
            request, _("Le dépôt de candidatures est réservé aux demandeurs d'emploi.")
        )
        return HttpResponseRedirect(prev_url)

    if not request.user.is_eligible_for_iae:
        messages.warning(
            request,
            _("Vous devez compléter vos informations avant de pouvoir postuler !"),
        )
        current_url = request.build_absolute_uri()
        redirect_to = reverse("dashboard:edit_user_info")
        return HttpResponseRedirect(
            f"{redirect_to}"
            f"?success_url={urllib.parse.quote(current_url)}"
            f"&prev_url={urllib.parse.quote(prev_url)}"
        )

    queryset = Siae.active_objects.prefetch_job_description_through()
    siae = get_object_or_404(queryset, siret=siret)

    form = JobApplicationForm(data=request.POST or None, user=request.user, siae=siae)

    if request.method == "POST" and form.is_valid():
        job_application = form.save()
        job_application.send(user=request.user)
        messages.success(request, _("Votre candidature a bien été envoyée !"))
        return HttpResponseRedirect(reverse("apply:list_for_job_seeker"))

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """

    job_applications = request.user.job_applications_sent.select_related(
        "job_seeker", "prescriber", "prescriber"
    ).prefetch_related("jobs")
    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {"job_applications_page": job_applications_page}
    return render(request, template_name, context)


@login_required
def list_for_prescriber(request, template_name="apply/list_for_prescriber.html"):
    """
    List of applications for a prescriber.
    """

    job_applications = request.user.job_applications_prescribed.select_related(
        "job_seeker", "prescriber", "prescriber"
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

    siret = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.active_objects.member_required(request.user)
    siae = get_object_or_404(queryset, siret=siret)

    job_applications = siae.job_applications_received.select_related(
        "job_seeker", "prescriber", "prescriber"
    ).prefetch_related("jobs")
    job_applications_page = pager(
        job_applications, request.GET.get("page"), items_per_page=10
    )

    context = {"siae": siae, "job_applications_page": job_applications_page}
    return render(request, template_name, context)


@login_required
def detail_for_siae(
    request, job_application_id, template_name="apply/detail_for_siae.html"
):
    """
    Detail of an application for an SIAE with the ability to give an answer.
    """

    queryset = (
        JobApplication.objects.siae_member_required(request.user)
        .select_related("job_seeker", "prescriber", "prescriber")
        .prefetch_related("jobs")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    last_log = (
        job_application.logs.select_related("user")
        .filter(to_state=job_application.state)
        .last()
    )

    process_form = JobApplicationProcessForm(data=request.POST or None)
    answer_form = JobApplicationAnswerForm(data=request.POST or None)

    if request.method == "POST":

        if process_form.is_valid():
            action = process_form.cleaned_data["action"]
            answer = process_form.cleaned_data["answer"]
            if action == process_form.ACTION_PROCESS:
                job_application.process(user=request.user)
                messages.success(request, _("Modification effectuée !"))
            elif action == process_form.ACTION_REJECT:
                job_application.reject(user=request.user, answer=answer)
                messages.success(request, _("Votre réponse a bien été envoyée !"))

        elif answer_form.is_valid():
            action = answer_form.cleaned_data["action"]
            answer = answer_form.cleaned_data["answer"]
            if action == answer_form.ACTION_ACCEPT:
                job_application.accept(user=request.user, answer=answer)
            elif action == answer_form.ACTION_REJECT:
                job_application.reject(user=request.user, answer=answer)
            messages.success(request, _("Votre réponse a bien été envoyée !"))

        return HttpResponseRedirect(request.get_full_path())

    context = {
        "answer_form": answer_form,
        "job_application": job_application,
        "last_log": last_log,
        "process_form": process_form,
    }
    return render(request, template_name, context)
