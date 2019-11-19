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

from itou.eligibility.criteria import CRITERIA
from itou.eligibility.models import EligibilityDiagnosis
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.perms.user import get_user_info
from itou.www.apply.forms import CheckJobSeekerInfoForm
from itou.www.apply.forms import CreateJobSeekerForm
from itou.www.apply.forms import JobSeekerExistsForm
from itou.www.apply.forms import SubmitJobApplicationForm


def valid_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(settings.ITOU_SESSION_JOB_APPLICATION_KEY)
        if not session_data or (session_data["to_siae_pk"] != kwargs["siae_pk"]):
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


@login_required
def start(request, siae_pk):
    """
    Entry point.
    """

    if request.user.is_siae_staff:
        raise PermissionDenied

    siae = get_object_or_404(Siae.active_objects, pk=siae_pk)

    # Start a fresh session.
    request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY] = {
        "job_seeker_pk": None,
        "to_siae_pk": siae.pk,
        "sender_pk": None,
        "sender_kind": None,
        "sender_prescriber_organization_pk": None,
        "job_description_id": request.GET.get("job_description_id"),
    }

    next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_sender(request, siae_pk):
    """
    Determine the sender.
    """
    user_info = get_user_info(request)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    session_data["sender_pk"] = user_info.user.pk
    session_data["sender_kind"] = user_info.kind
    session_data["sender_prescriber_organization_pk"] = None
    if user_info.prescriber_organization:
        session_data[
            "sender_prescriber_organization_pk"
        ] = user_info.prescriber_organization.pk

    next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae_pk})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_job_seeker(
    request, siae_pk, template_name="apply/submit_step_job_seeker.html"
):
    """
    Determine the job seeker.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae_pk})

    # The user submit an application for himself.
    if request.user.is_job_seeker:
        session_data["job_seeker_pk"] = request.user.pk
        return HttpResponseRedirect(next_url)

    siae = get_object_or_404(Siae.active_objects, pk=session_data["to_siae_pk"])

    form = JobSeekerExistsForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_seeker = form.get_job_seeker_from_email()

        if job_seeker:
            session_data["job_seeker_pk"] = job_seeker.pk
            return HttpResponseRedirect(next_url)

        args = urlencode({"email": form.cleaned_data["email"]})
        next_url = reverse("apply:step_create_job_seeker", kwargs={"siae_pk": siae.pk})
        return HttpResponseRedirect(f"{next_url}?{args}")

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_check_job_seeker_info(
    request, siae_pk, template_name="apply/submit_step_job_seeker_check_info.html"
):
    """
    Check job seeker info.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])
    next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae_pk})

    # Ensure that the job seeker has a birthdate.
    if job_seeker.birthdate:
        return HttpResponseRedirect(next_url)

    siae = get_object_or_404(Siae.active_objects, pk=session_data["to_siae_pk"])

    form = CheckJobSeekerInfoForm(instance=job_seeker, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(next_url)

    context = {"form": form, "siae": siae, "job_seeker": job_seeker}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_create_job_seeker(
    request, siae_pk, template_name="apply/submit_step_job_seeker_create.html"
):
    """
    Create a job seeker.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae.active_objects, pk=session_data["to_siae_pk"])

    form = CreateJobSeekerForm(
        proxy_user=request.user,
        data=request.POST or None,
        initial={"email": request.GET.get("email")},
    )

    if request.method == "POST" and form.is_valid():
        job_seeker = form.save()
        session_data["job_seeker_pk"] = job_seeker.pk
        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_eligibility(
    request, siae_pk, template_name="apply/submit_step_eligibility.html"
):
    """
    Check eligibility.
    """
    user_info = get_user_info(request)
    next_url = reverse("apply:step_application", kwargs={"siae_pk": siae_pk})

    # This step is only required for an authorized prescriber.
    if not user_info.is_authorized_prescriber:
        return HttpResponseRedirect(next_url)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae.active_objects, pk=session_data["to_siae_pk"])
    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])

    # This step is only required if the job seeker hasn't already
    # an eligibility diagnosis.
    if job_seeker.has_eligibility_diagnosis:
        return HttpResponseRedirect(next_url)

    if request.method == "POST":
        EligibilityDiagnosis.create_diagnosis(job_seeker, user_info)
        messages.success(request, _("Éligibilité confirmée !"))
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "job_seeker": job_seeker, "eligibility_criteria": CRITERIA}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_application(
    request, siae_pk, template_name="apply/submit_step_application.html"
):
    """
    Submit a job application.
    """
    queryset = Siae.active_objects.prefetch_job_description_through()
    siae = get_object_or_404(queryset, pk=siae_pk)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    initial_data = {"selected_jobs": [session_data["job_description_id"]]}
    form = SubmitJobApplicationForm(
        data=request.POST or None, siae=siae, initial=initial_data
    )

    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])

    if request.method == "POST" and form.is_valid():

        sender_prescriber_organization_pk = session_data.get(
            "sender_prescriber_organization_pk"
        )

        job_application = form.save(commit=False)
        job_application.job_seeker = job_seeker
        job_application.sender = get_user_model().objects.get(
            pk=session_data["sender_pk"]
        )
        job_application.sender_kind = session_data["sender_kind"]
        if sender_prescriber_organization_pk:
            job_application.sender_prescriber_organization = PrescriberOrganization.objects.get(
                pk=sender_prescriber_organization_pk
            )
        job_application.to_siae = siae
        job_application.save()

        for job in form.cleaned_data["selected_jobs"]:
            job_application.selected_jobs.add(job)

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
