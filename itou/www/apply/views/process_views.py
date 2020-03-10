from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.perms.user import get_user_info
from itou.www.apply.forms import (
    AcceptForm,
    AnswerForm,
    JobSeekerPoleEmploiStatusForm,
    RefusalForm,
)


def check_waiting_period(approvals_wrapper, job_application):
    """
    This should be an edge case.
    An approval may expire between the time an application is sent and
    the time it is accepted.
    Only "authorized prescribers" can bypass an approval in waiting period.
    """
    if (
        approvals_wrapper.has_in_waiting_period
        and not job_application.is_sent_by_authorized_prescriber
    ):
        error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        raise PermissionDenied(error)


@login_required
def details_for_siae(
    request, job_application_id, template_name="apply/process_details.html"
):
    """
    Detail of an application for an SIAE with the ability to give an answer.
    """

    queryset = (
        JobApplication.objects.siae_member_required(request.user)
        .select_related(
            "job_seeker",
            "sender",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae",
            "approval",
        )
        .prefetch_related("selected_jobs__appellation")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = (
        job_application.logs.select_related("user").all().order_by("timestamp")
    )

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "job_application": job_application,
        "transition_logs": transition_logs,
    }
    return render(request, template_name, context)


@login_required
@require_http_methods(["POST"])
def process(request, job_application_id):
    """
    Trigger the `process` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    job_application.process(user=request.user)

    next_url = reverse(
        "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
    )
    return HttpResponseRedirect(next_url)


@login_required
def refuse(request, job_application_id, template_name="apply/process_refuse.html"):
    """
    Trigger the `refuse` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    form = RefusalForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_application.refusal_reason = form.cleaned_data["refusal_reason"]
        job_application.answer = form.cleaned_data["answer"]
        job_application.save()

        job_application.refuse(user=request.user)

        messages.success(request, _("Modification effectuée."))

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)
    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "form": form,
        "job_application": job_application,
    }
    return render(request, template_name, context)


@login_required
def postpone(request, job_application_id, template_name="apply/process_postpone.html"):
    """
    Trigger the `postpone` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    approvals_wrapper = job_application.job_seeker.approvals_wrapper
    check_waiting_period(approvals_wrapper, job_application)

    form = AnswerForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_application.answer = form.cleaned_data["answer"]
        job_application.save()

        job_application.postpone(user=request.user)

        messages.success(request, _("Modification effectuée."))

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "form": form,
        "job_application": job_application,
    }
    return render(request, template_name, context)


@login_required
def accept(request, job_application_id, template_name="apply/process_accept.html"):
    """
    Trigger the `accept` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    approvals_wrapper = job_application.job_seeker.approvals_wrapper
    check_waiting_period(approvals_wrapper, job_application)

    forms = []

    # Ask the SIAE to verify the job seeker's Pôle emploi status.
    # This will ensure a smooth Approval delivery.
    form_pe_status = None
    if job_application.to_siae.is_subject_to_eligibility_rules:
        form_pe_status = form_pe_status = JobSeekerPoleEmploiStatusForm(
            instance=job_application.job_seeker, data=request.POST or None
        )
        forms.append(form_pe_status)

    form_accept = AcceptForm(instance=job_application, data=request.POST or None)
    forms.append(form_accept)

    if request.method == "POST" and all([form.is_valid() for form in forms]):

        if form_pe_status:
            form_pe_status.save()

        job_application = form_accept.save()
        job_application.accept(user=request.user)

        messages.success(request, _("Embauche acceptée !"))

        if job_application.to_siae.is_subject_to_eligibility_rules:
            if job_application.approval:
                messages.success(
                    request,
                    _(
                        "Le numéro d'agrément peut être utilisé pour "
                        "la déclaration de la personne dans l'ASP."
                    ),
                )
            else:
                messages.success(
                    request,
                    mark_safe(
                        _(
                            "Il n'est pas nécessaire de demander le numéro d'agrément "
                            "à votre interlocuteur Pôle emploi.<br>"
                            "Le numéro d'agrément sera indiqué sur cette page - "
                            "vous serez prévenu par email dès qu'il sera disponible.<br>"
                            "Ce numéro pourra être utilisé pour la déclaration de la "
                            "personne dans l'ASP."
                        )
                    ),
                )

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "form_accept": form_accept,
        "form_pe_status": form_pe_status,
        "job_application": job_application,
    }
    return render(request, template_name, context)


@login_required
def eligibility(
    request, job_application_id, template_name="apply/process_eligibility.html"
):
    """
    Check eligibility.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(
        queryset, id=job_application_id, state=JobApplicationWorkflow.STATE_PROCESSING
    )

    if not job_application.to_siae.is_subject_to_eligibility_rules:
        raise Http404()

    if request.method == "POST":
        if not request.POST.get("confirm-eligibility") == "1":
            messages.error(
                request, _("Vous devez confirmer l'éligibilité du candidat.")
            )
        else:
            user_info = get_user_info(request)
            EligibilityDiagnosis.create_diagnosis(job_application.job_seeker, user_info)
            messages.success(request, _("Éligibilité confirmée !"))
            next_url = reverse(
                "apply:details_for_siae",
                kwargs={"job_application_id": job_application.id},
            )
            return HttpResponseRedirect(next_url)

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "job_application": job_application,
    }
    return render(request, template_name, context)
