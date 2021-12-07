from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.users.models import User
from itou.utils.perms.user import get_user_info
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    CheckJobSeekerInfoForm,
    CheckJobSeekerNirForm,
    CreateJobSeekerForm,
    SubmitJobApplicationForm,
    UserExistsForm,
)
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


def valid_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(settings.ITOU_SESSION_JOB_APPLICATION_KEY)
        if not session_data or (session_data["to_siae_pk"] != kwargs["siae_pk"]):
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


def get_approvals_wrapper(request, job_seeker, siae):
    """
    Returns an `ApprovalsWrapper` if possible or stop
    the job application submit process.
    This works only when the `job_seeker` is known.
    """
    user_info = get_user_info(request)
    approvals_wrapper = job_seeker.approvals_wrapper

    if approvals_wrapper.cannot_bypass_waiting_period(
        siae=siae, sender_prescriber_organization=user_info.prescriber_organization
    ):
        error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        if user_info.user == job_seeker:
            error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_USER
        raise PermissionDenied(error)

    if approvals_wrapper.has_valid and approvals_wrapper.latest_approval.is_pass_iae:

        # Ensure that an existing approval can be unsuspended.
        if not approvals_wrapper.latest_approval.can_update_suspension:
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
        raise PermissionDenied("Vous ne pouvez postuler pour un candidat que dans votre structure.")

    # Refuse all applications except those issued by the SIAE
    if siae.block_job_applications and not siae.has_member(request.user):
        # Message only visible in DEBUG
        raise Http404("Cette organisation n'accepte plus de candidatures pour le moment.")

    back_url = get_safe_url(request, "back_url")

    # Start a fresh session.
    request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY] = {
        "back_url": back_url,
        "job_seeker_pk": None,
        "nir": None,
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

    request.session.modified = True

    next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae_pk})
    return HttpResponseRedirect(next_url)


@login_required
@valid_session_required
def step_check_job_seeker_nir(request, siae_pk, template_name="apply/submit_step_check_job_seeker_nir.html"):
    """
    Ensure the job seeker has a NIR. If not and if possible, update it.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae_pk})
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])
    job_seeker = None
    job_seeker_name = None

    # The user submits an application for himself.
    if request.user.is_job_seeker:
        session_data["job_seeker_pk"] = request.user.pk
        request.session.modified = True
        job_seeker = request.user
        if job_seeker.nir:
            return HttpResponseRedirect(next_url)

    form = CheckJobSeekerNirForm(job_seeker=job_seeker, data=request.POST or None)
    preview_mode = False

    if request.method == "POST" and form.is_valid():
        nir = form.cleaned_data["nir"]

        if request.user.is_job_seeker:
            job_seeker.nir = nir
            job_seeker.save()
            return HttpResponseRedirect(next_url)

        job_seeker = form.get_job_seeker()
        if not job_seeker:
            # Redirect to search by e-mail address.
            session_data["nir"] = nir
            request.session.modified = True
            next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae_pk})
            return HttpResponseRedirect(next_url)

        if form.data.get("confirm"):
            # Job seeker found for the given NIR.
            session_data["job_seeker_pk"] = job_seeker.pk
            request.session.modified = True
            return HttpResponseRedirect(next_url)

        if form.data.get("preview"):
            preview_mode = True
            job_seeker_name = job_seeker.get_full_name()
            if request.user.is_prescriber and not request.user.is_prescriber_with_authorized_org:
                # Don't display personal information to unauthorized members.
                job_seeker_name = f"{job_seeker.first_name[0]}… {job_seeker.last_name[0]}…"
        elif form.data.get("cancel"):
            form = CheckJobSeekerNirForm()

    if request.method == "POST" and form.data.get("skip"):
        # Redirect to search by e-mail address.
        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae_pk})
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "job_seeker": job_seeker,
        "job_seeker_name": job_seeker_name,
        "preview_mode": preview_mode,
        "siae": siae,
    }
    return render(request, template_name, context)


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
        return HttpResponseRedirect(next_url)

    job_seeker_name = None
    form = UserExistsForm(data=request.POST or None)
    nir = session_data.get("nir")
    can_add_nir = False
    preview_mode = False
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])

    if request.method == "POST" and form.is_valid():
        job_seeker = form.get_user()

        if job_seeker:
            # Go to the next step.
            can_add_nir = nir and request.user.can_add_nir(job_seeker)
            if request.POST.get("save"):
                session_data["job_seeker_pk"] = job_seeker.pk
                request.session.modified = True
                if can_add_nir:
                    job_seeker.nir = session_data["nir"]
                    job_seeker.save()
                return HttpResponseRedirect(next_url)

            # Display a modal containing more information.
            if request.POST.get("preview"):
                preview_mode = True
                job_seeker_name = job_seeker.get_full_name()
                if request.user.is_prescriber and not request.user.is_prescriber_with_authorized_org:
                    # Don't display personal information to unauthorized members.
                    job_seeker_name = f"{job_seeker.first_name[0]}… {job_seeker.last_name[0]}…"

            # Create a new form to start from new.
            elif request.POST.get("cancel"):
                msg = mark_safe(
                    f"L'email <b>{ form.data['email'] }</b> est déjà utilisé par un autre candidat "
                    "sur la Plateforme.<br>"
                    "Merci de renseigner <b>l'adresse email personnelle et unique</b> "
                    "du candidat pour lequel vous souhaitez postuler."
                )
                form = UserExistsForm()
                messages.warning(request, msg)

        else:
            args = urlencode({"email": form.cleaned_data["email"]})
            next_url = reverse("apply:step_create_job_seeker", kwargs={"siae_pk": siae.pk})
            return HttpResponseRedirect(f"{next_url}?{args}")

    context = {
        "can_add_nir": can_add_nir,
        "form": form,
        "job_seeker_name": job_seeker_name,
        "nir": nir,
        "preview_mode": preview_mode,
        "siae": siae,
    }
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_check_job_seeker_info(request, siae_pk, template_name="apply/submit_step_job_seeker_check_info.html"):
    """
    Ensure the job seeker has all required info.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    job_seeker = get_object_or_404(User, pk=session_data["job_seeker_pk"])
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)
    next_url = reverse("apply:step_check_prev_applications", kwargs={"siae_pk": siae_pk})

    # Check required info that will allow us to find a pre-existing approval.
    has_required_info = job_seeker.birthdate and (
        job_seeker.pole_emploi_id or job_seeker.lack_of_pole_emploi_id_reason
    )

    if has_required_info:
        return HttpResponseRedirect(next_url)

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

    nir = session_data["nir"]
    form = CreateJobSeekerForm(
        proxy_user=request.user, nir=nir, data=request.POST or None, initial={"email": request.GET.get("email")}
    )

    if request.method == "POST" and form.is_valid():
        job_seeker = form.save()
        session_data["job_seeker_pk"] = job_seeker.pk
        request.session.modified = True
        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form}
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_check_prev_applications(request, siae_pk, template_name="apply/submit_step_check_prev_applications.html"):
    """
    Check previous job applications to avoid duplicates.
    """
    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])
    job_seeker = get_object_or_404(User, pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)
    prev_applications = job_seeker.job_applications.filter(to_siae=siae)

    # Limit the possibility of applying to the same SIAE for 24 hours.
    if not request.user.is_siae_staff and prev_applications.created_in_past(hours=24).exists():
        if request.user == job_seeker:
            msg = "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures."
        else:
            msg = "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures."
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
    job_seeker = get_object_or_404(User, pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)

    skip = (
        # Only "authorized prescribers" can perform an eligibility diagnosis.
        not user_info.is_authorized_prescriber
        # Eligibility diagnosis already performed.
        or job_seeker.has_valid_diagnosis()
    )

    if skip:
        return HttpResponseRedirect(next_url)

    data = request.POST if request.method == "POST" else None
    form_administrative_criteria = AdministrativeCriteriaForm(request.user, siae=None, data=data)

    if request.method == "POST" and form_administrative_criteria.is_valid():
        EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=form_administrative_criteria.cleaned_data
        )
        messages.success(request, "Éligibilité confirmée !")
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

    job_seeker = get_object_or_404(User, pk=session_data["job_seeker_pk"])
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)

    if request.method == "POST" and form.is_valid():
        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae_pk})

        # Prevent multiple rapid clicks on the submit button to create multiple
        # job applications.
        if job_seeker.job_applications.filter(to_siae=siae).created_in_past(seconds=10).exists():
            return HttpResponseRedirect(next_url)

        job_application = form.save(commit=False)
        job_application.job_seeker = job_seeker

        job_application.sender = get_object_or_404(User, pk=session_data["sender_pk"])
        job_application.sender_kind = session_data["sender_kind"]
        if sender_prescriber_organization_pk := session_data.get("sender_prescriber_organization_pk"):
            job_application.sender_prescriber_organization = get_object_or_404(
                PrescriberOrganization, pk=sender_prescriber_organization_pk
            )
        if sender_siae_pk := session_data.get("sender_siae_pk"):
            job_application.sender_siae = get_object_or_404(Siae, pk=sender_siae_pk)
        job_application.to_siae = siae
        job_application.save()

        for job in form.cleaned_data["selected_jobs"]:
            job_application.selected_jobs.add(job)

        if job_application.is_spontaneous:
            notification = NewSpontaneousJobAppEmployersNotification(job_application=job_application)
        else:
            notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)

        notification.send()
        base_url = request.build_absolute_uri("/")[:-1]
        job_application.email_new_for_job_seeker(base_url=base_url).send()

        if job_application.is_sent_by_proxy:
            job_application.email_new_for_prescriber.send()

        return HttpResponseRedirect(next_url)

    s3_upload = S3Upload(kind="resume")
    s3_form_values = s3_upload.form_values
    s3_upload_config = s3_upload.config

    context = {
        "siae": siae,
        "form": form,
        "job_seeker": job_seeker,
        "approvals_wrapper": approvals_wrapper,
        "s3_form_values": s3_form_values,
        "s3_upload_config": s3_upload_config,
    }
    return render(request, template_name, context)


@login_required
@valid_session_required
def step_application_sent(request, siae_pk, template_name="apply/submit_step_application_sent.html"):
    if request.user.is_siae_staff:
        dashboard_url = reverse("apply:list_for_siae")
        messages.success(request, "Candidature bien envoyée !")
        return HttpResponseRedirect(dashboard_url)

    session_data = request.session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
    back_url = get_safe_url(request=request, url=session_data["back_url"])
    job_seeker = get_object_or_404(User, pk=session_data["job_seeker_pk"])
    siae = get_object_or_404(Siae, pk=session_data["to_siae_pk"])

    context = {
        "back_url": back_url,
        "job_seeker": job_seeker,
        "siae": siae,
    }
    return render(request, template_name, context)
