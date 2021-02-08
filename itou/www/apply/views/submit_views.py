from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.notifications import NewJobApplicationSiaeEmailNotification
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.perms.user import get_user_info
from itou.utils.resume.forms import ResumeFormMixin
from itou.utils.tokens import resume_signer
from itou.www.apply.forms import CheckJobSeekerInfoForm, CreateJobSeekerForm, SubmitJobApplicationForm, UserExistsForm
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


def valid_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(settings.ITOU_SESSION_JOB_APPLICATION_KEY)
        if not session_data or (session_data["to_siae_pk"] != kwargs["siae_pk"]):
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


def get_approvals_wrapper(request, job_seeker):
    """
    Returns an `ApprovalsWrapper` if possible or stop
    the job application submit process.
    This works only when the `job_seeker` is known.
    """
    user_info = get_user_info(request)
    approvals_wrapper = job_seeker.approvals_wrapper
    # Ensure that an existing approval is not in waiting period.
    # Only "authorized prescribers" can bypass an approval in waiting period.
    if approvals_wrapper.has_in_waiting_period and not user_info.is_authorized_prescriber:
        error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        if user_info.user == job_seeker:
            error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_USER
        raise PermissionDenied(error)
    # Ensure that an existing approval is not suspended.
    if (
        approvals_wrapper.has_valid
        and approvals_wrapper.latest_approval.is_pass_iae
        and approvals_wrapper.latest_approval.is_suspended
    ):
        error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_PROXY
        if user_info.user == job_seeker:
            error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_USER
        raise PermissionDenied(error)
    return approvals_wrapper


@login_required
def start(request, siae_pk):
    """
    Entry point.
    """

    siae = get_object_or_404(Siae, pk=siae_pk)

    if request.user.is_siae_staff and not siae.has_member(request.user):
        raise PermissionDenied(_("Vous ne pouvez postuler pour un candidat que dans votre structure."))

    # Refuse all applications except those issued by the SIAE
    if siae.block_job_applications and not siae.has_member(request.user):
        raise Http404(_("Cette organisation n'accepte plus de candidatures pour le moment."))

    # Start a fresh session.
    request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY] = {
        "job_seeker_pk": None,
        "to_siae_pk": siae.pk,
        "sender_pk": None,
        "sender_kind": None,
        "sender_siae_pk": None,
        "sender_prescriber_organization_pk": None,
        "job_description_id": request.GET.get("job_description_id"),
    }

    next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_sender(request, siae_pk):
    """
    Determine info about the sender.
    """
    user_info = get_user_info(request)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    session_data["sender_pk"] = user_info.user.pk
    session_data["sender_kind"] = user_info.kind

    if user_info.prescriber_organization:
        session_data["sender_prescriber_organization_pk"] = user_info.prescriber_organization.pk

    if user_info.siae:
        session_data["sender_siae_pk"] = user_info.siae.pk

    next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae_pk})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_job_seeker(request, siae_pk, template_name="apply/submit_step_job_seeker.html"):
    """
    Determine the job seeker, in the cases where the application is sent by a proxy.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae_pk})

    # The user submit an application for himself.
    if request.user.is_job_seeker:
        session_data["job_seeker_pk"] = request.user.pk
        return HttpResponseRedirect(next_url)

    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])

    form = UserExistsForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_seeker = form.get_user()

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
def step_check_job_seeker_info(request, siae_pk, template_name="apply/submit_step_job_seeker_check_info.html"):
    """
    Ensure the job seeker has all required info.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker)
    next_url = reverse("apply:step_check_prev_applications", kwargs={"siae_pk": siae_pk})

    # Check required info that will allow us to find a pre-existing approval.
    has_required_info = job_seeker.birthdate and (
        job_seeker.pole_emploi_id or job_seeker.lack_of_pole_emploi_id_reason
    )

    if has_required_info:
        return HttpResponseRedirect(next_url)

    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])

    form = CheckJobSeekerInfoForm(instance=job_seeker, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(next_url)

    context = {"form": form, "siae": siae, "job_seeker": job_seeker, "approvals_wrapper": approvals_wrapper}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_create_job_seeker(request, siae_pk, template_name="apply/submit_step_job_seeker_create.html"):
    """
    Create a job seeker if he can't be found in the DB.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])

    form = CreateJobSeekerForm(
        proxy_user=request.user, data=request.POST or None, initial={"email": request.GET.get("email")}
    )

    if request.method == "POST" and form.is_valid():
        job_seeker = form.save()
        session_data["job_seeker_pk"] = job_seeker.pk
        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        if request.GET.get("resume"):
            next_url = reverse("apply:step_send_resume", kwargs={"siae_pk": siae.pk})
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_send_resume(request, siae_pk, template_name="apply/submit_step_send_resume.html"):
    """
    Updates user's resume following the next steps:
    - Prescriber uploads a file using Typeform's embed form.
    - When Typeform receives a new entry, it performs a POST on `/update-resume-link`
    - This view updates job seeker's `resume_link` attribute.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])
    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])
    job_seeker_signed_pk = resume_signer.sign(job_seeker.pk)

    form = ResumeFormMixin(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("resume_link"):
            job_seeker.resume_link = form.cleaned_data.get("resume_link")
            job_seeker.save()
        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "job_seeker_signed_pk": job_seeker_signed_pk, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_check_prev_applications(request, siae_pk, template_name="apply/submit_step_check_prev_applications.html"):
    """
    Check previous job applications to avoid duplicates.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])
    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker)
    prev_applications = job_seeker.job_applications.filter(to_siae=siae)

    # Limit the possibility of applying to the same SIAE for 24 hours.
    # ---
    # Some employers cancel applications because they cannot change information.
    # Then they are contacting the support to say that they cannot apply again.
    # Pending a clean solution to this issue, we drop the 24-hour restriction for employers only.
    # This allow them to submit a clean application.
    if not request.user.is_siae_staff and prev_applications.created_in_past_hours(24).exists():
        if request.user == job_seeker:
            msg = _("Vous avez déjà postulé chez cet employeur durant les dernières 24 heures.")
        else:
            msg = _("Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.")
        raise PermissionDenied(msg)

    next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})

    if not prev_applications.exists():
        return HttpResponseRedirect(next_url)

    # At this point we know that the candidate is applying to an SIAE
    # where he or she has already applied.
    # Allow a new job application if the user confirm it despite the
    # duplication warning.
    if request.method == "POST" and request.POST.get("force_new_application") == "force":
        return HttpResponseRedirect(next_url)

    context = {
        "job_seeker": job_seeker,
        "siae": siae,
        "prev_application": prev_applications.latest("created_at"),
        "approvals_wrapper": approvals_wrapper,
    }
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_eligibility(request, siae_pk, template_name="apply/submit_step_eligibility.html"):
    """
    Check eligibility (as an authorized prescriber).
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])
    next_url = reverse("apply:step_application", kwargs={"siae_pk": siae_pk})

    if not siae.is_subject_to_eligibility_rules:
        return HttpResponseRedirect(next_url)

    user_info = get_user_info(request)
    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker)

    skip = (
        # Only "authorized prescribers" can perform an eligibility diagnosis.
        not user_info.is_authorized_prescriber
        # Eligibility diagnosis already performed.
        or EligibilityDiagnosis.objects.has_considered_valid(job_seeker)
    )

    if skip:
        return HttpResponseRedirect(next_url)

    data = request.POST if request.method == "POST" else None
    form_administrative_criteria = AdministrativeCriteriaForm(request.user, siae=None, data=data)

    if request.method == "POST" and form_administrative_criteria.is_valid():
        EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=form_administrative_criteria.cleaned_data
        )
        messages.success(request, _("Éligibilité confirmée !"))
        return HttpResponseRedirect(next_url)

    context = {
        "siae": siae,
        "job_seeker": job_seeker,
        "approvals_wrapper": approvals_wrapper,
        "form_administrative_criteria": form_administrative_criteria,
    }
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_application(request, siae_pk, template_name="apply/submit_step_application.html"):
    """
    Create and submit the job application.
    """
    queryset = Siae.objects.prefetch_job_description_through()
    siae = get_object_or_404(queryset, pk=siae_pk)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    initial_data = {"selected_jobs": [session_data["job_description_id"]]}
    form = SubmitJobApplicationForm(data=request.POST or None, siae=siae, initial=initial_data)

    job_seeker = get_user_model().objects.get(pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker)

    if request.method == "POST" and form.is_valid():

        next_url = reverse("apply:list_for_job_seeker")
        if request.user.is_prescriber:
            next_url = reverse("apply:list_for_prescriber")
        elif request.user.is_siae_staff:
            next_url = reverse("apply:list_for_siae")

        # Prevent multiple rapid clicks on the submit button to create multiple
        # job applications.
        if job_seeker.job_applications.filter(to_siae=siae).created_in_past_hours(1).exists():
            return HttpResponseRedirect(next_url)

        sender_prescriber_organization_pk = session_data.get("sender_prescriber_organization_pk")
        sender_siae_pk = session_data.get("sender_siae_pk")
        job_application = form.save(commit=False)
        job_application.job_seeker = job_seeker
        job_application.sender = get_user_model().objects.get(pk=session_data["sender_pk"])
        job_application.sender_kind = session_data["sender_kind"]
        if sender_prescriber_organization_pk:
            job_application.sender_prescriber_organization = PrescriberOrganization.objects.get(
                pk=sender_prescriber_organization_pk
            )
        if sender_siae_pk:
            job_application.sender_siae = Siae.objects.get(pk=sender_siae_pk)
        job_application.to_siae = siae
        job_application.save()

        for job in form.cleaned_data["selected_jobs"]:
            job_application.selected_jobs.add(job)

        notification = NewJobApplicationSiaeEmailNotification(job_application=job_application)
        notification.send()
        base_url = request.build_absolute_uri("/")[:-1]
        job_application.email_new_for_job_seeker(base_url=base_url).send()

        if job_application.is_sent_by_proxy:
            job_application.email_new_for_prescriber.send()

        messages.success(request, _("Candidature bien envoyée !"))

        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form, "job_seeker": job_seeker, "approvals_wrapper": approvals_wrapper}
    return render(request, template_name, context)
