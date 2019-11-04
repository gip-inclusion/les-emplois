from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import ugettext as _

from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.www.apply.forms import (
    CheckJobSeekerForm,
    CreateJobSeekerForm,
    SubmitJobApplicationForm,
)


def valid_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(settings.ITOU_SESSION_JOB_APPLICATION_KEY)
        if not session_data or (session_data["to_siae_siret"] != str(kwargs["siret"])):
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


@login_required
def start(request, siret):
    """
    Entry point.
    """

    if request.user.is_siae_staff:
        raise PermissionDenied

    siae = get_object_or_404(Siae.active_objects, siret=siret)

    # Start a fresh session.
    request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY] = {
        "to_siae": siae.pk,
        "to_siae_siret": siae.siret,
    }

    next_url = reverse("apply:step_sender", kwargs={"siret": siae.siret})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_sender(request, siret):
    """
    Determine the sender.
    """

    sender = request.user.pk
    sender_kind = JobApplication.SENDER_KIND_JOB_SEEKER
    prescriber_organization = None

    if request.user.is_prescriber:
        sender_kind = JobApplication.SENDER_KIND_PRESCRIBER
        pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
        if pk:
            queryset = PrescriberOrganization.objects.member_required(request.user)
            prescriber_organization = get_object_or_404(queryset, pk=pk)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    session_data["sender"] = sender
    session_data["sender_kind"] = sender_kind
    session_data["sender_prescriber_organization"] = (
        prescriber_organization.pk if prescriber_organization else None
    )

    next_url = reverse("apply:step_job_seeker", kwargs={"siret": siret})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_job_seeker(request, siret, template_name="apply/submit_step_job_seeker.html"):
    """
    Determine the job seeker.
    """

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]

    # The user submit an application for himself.
    if request.user.is_job_seeker:
        session_data["job_seeker"] = request.user.pk
        next_url = reverse("apply:step_application", kwargs={"siret": siret})
        return HttpResponseRedirect(next_url)

    siae = get_object_or_404(Siae.active_objects, pk=session_data["to_siae"])

    form = CheckJobSeekerForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_seeker = form.get_job_seeker_from_email()

        if not job_seeker:
            args = urlencode({"email": form.cleaned_data["email"]})
            next_url = reverse("apply:step_create_job_seeker", kwargs={"siret": siret})
            return HttpResponseRedirect(f"{next_url}?{args}")

        session_data["job_seeker"] = job_seeker.pk
        next_url = reverse("apply:step_application", kwargs={"siret": siret})
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_create_job_seeker(
    request, siret, template_name="apply/submit_step_create_job_seeker.html"
):
    """
    Create a job seeker.
    """

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae.active_objects, pk=session_data["to_siae"])

    form = CreateJobSeekerForm(
        proxy_user=request.user,
        data=request.POST or None,
        initial={"email": request.GET.get("email")},
    )

    if request.method == "POST" and form.is_valid():
        job_seeker = form.save()
        session_data["job_seeker"] = job_seeker.pk
        next_url = reverse("apply:step_application", kwargs={"siret": siret})
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_application(
    request, siret, template_name="apply/submit_step_application.html"
):
    """
    Submit a job application.
    """

    queryset = Siae.active_objects.prefetch_job_description_through()
    siae = get_object_or_404(queryset, siret=siret)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    form = SubmitJobApplicationForm(data=request.POST or None, siae=siae)

    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker"])

    if request.method == "POST" and form.is_valid():

        sender_prescriber_organization = session_data.get(
            "sender_prescriber_organization"
        )
        if sender_prescriber_organization:
            sender_prescriber_organization = PrescriberOrganization.objects.get(
                pk=sender_prescriber_organization
            )

        job_application = form.save(commit=False)
        job_application.job_seeker = job_seeker
        job_application.sender = get_user_model().objects.get(pk=session_data["sender"])
        job_application.sender_kind = session_data["sender_kind"]
        job_application.sender_prescriber_organization = sender_prescriber_organization
        job_application.to_siae = siae
        job_application.save()

        for job in form.cleaned_data["jobs"]:
            job_application.jobs.add(job)

        job_application.email_new_for_siae.send()

        messages.success(request, _("Votre candidature a bien été envoyée !"))

        if request.user.is_job_seeker:
            next_url = reverse("apply:list_for_job_seeker")
        elif request.user.is_prescriber:
            next_url = reverse("apply:list_for_prescriber")
        # elif request.user.is_siae_staff:
        #     next_url = reverse("apply:list_for_siae")
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form, "job_seeker": job_seeker}
    return render(request, template_name, context)
