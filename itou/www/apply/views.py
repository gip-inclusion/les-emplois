from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.translation import ugettext as _

from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.apply.forms import JobApplicationForm, JobApplicationAnswerForm


@login_required
@user_passes_test(
    lambda user: user.is_job_seeker, login_url="/", redirect_field_name=None
)
def submit_for_job_seeker(
    request, siret, template_name="apply/submit_for_job_seeker.html"
):
    """
    Submit a job application as a job seeker.
    """

    # TODO: ensure the use can apply.

    queryset = Siae.active_objects.prefetch_jobs_through()
    siae = get_object_or_404(queryset, siret=siret)

    form = JobApplicationForm(data=request.POST or None, user=request.user, siae=siae)

    if request.method == "POST" and form.is_valid():
        job_application = form.save()
        job_application.send(user=request.user)
        messages.success(request, _("Votre candidature a bien été envoyée !"))
        return HttpResponseRedirect("/")

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
def list_for_job_seeker(request, template_name="apply/list_for_job_seeker.html"):
    """
    List of applications for a job seeker.
    """

    job_applications = request.user.job_applications_sent.select_related(
        "job_seeker", "prescriber_user", "prescriber"
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
        "job_seeker", "prescriber_user", "prescriber"
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
        .select_related("job_seeker", "prescriber_user", "prescriber")
        .prefetch_related("jobs")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    last_log = (
        job_application.logs.select_related("user")
        .filter(to_state=job_application.state)
        .last()
    )

    form = JobApplicationAnswerForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        answer_kind = form.cleaned_data["answer_kind"]
        answer = form.cleaned_data["answer"]

        if answer_kind == form.ANSWER_KIND_ACCEPT:
            job_application.accept(user=request.user, answer=answer)

        elif answer_kind == form.ANSWER_KIND_REJECT:
            job_application.reject(user=request.user, answer=answer)

        messages.success(request, _("Votre réponse a bien été envoyée !"))
        return HttpResponseRedirect(request.get_full_path())

    context = {
        "answer_form": form,
        "job_application": job_application,
        "last_log": last_log,
    }
    return render(request, template_name, context)
