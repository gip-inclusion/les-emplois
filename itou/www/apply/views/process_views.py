from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods
from django_xworkflows import models as xwf_models

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.perms.user import get_user_info
from itou.www.apply.forms import AcceptForm, AnswerForm, JobSeekerPoleEmploiStatusForm, RefusalForm, UserAddressForm
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm, ConfirmEligibilityForm


def check_waiting_period(approvals_wrapper, job_application):
    """
    This should be an edge case.
    An approval may expire between the time an application is sent and
    the time it is accepted.
    Only "authorized prescribers" can bypass an approval in waiting period.
    """
    if approvals_wrapper.has_in_waiting_period and not job_application.is_sent_by_authorized_prescriber:
        error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        raise PermissionDenied(error)


@login_required
def details_for_siae(request, job_application_id, template_name="apply/process_details.html"):
    """
    Detail of an application for an SIAE with the ability:
    - to update start date of a contract (provided given date is in the future),
    - to give an answer.
    """
    queryset = (
        JobApplication.objects.siae_member_required(request.user)
        .not_archived()
        .select_related("job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae", "approval")
        .prefetch_related("selected_jobs__appellation")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = job_application.logs.select_related("user").all().order_by("timestamp")
    cancellation_days = JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED

    eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
        job_application.job_seeker, for_siae=job_application.to_siae
    )

    approval_can_be_suspended_by_siae = job_application.approval and job_application.approval.can_be_suspended_by_siae(
        job_application.to_siae
    )
    approval_can_be_prolonged_by_siae = job_application.approval and job_application.approval.can_be_prolonged_by_siae(
        job_application.to_siae
    )

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "approval_can_be_suspended_by_siae": approval_can_be_suspended_by_siae,
        "approval_can_be_prolonged_by_siae": approval_can_be_prolonged_by_siae,
        "cancellation_days": cancellation_days,
        "eligibility_diagnosis": eligibility_diagnosis,
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

    try:
        # After each successful transition, a save() is performed by django-xworkflows.
        job_application.process(user=request.user)
    except xwf_models.InvalidTransitionError:
        messages.error(request, "Action déjà effectuée.")

    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
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

        try:
            # After each successful transition, a save() is performed by django-xworkflows.
            job_application.refusal_reason = form.cleaned_data["refusal_reason"]
            job_application.answer = form.cleaned_data["answer"]
            job_application.refuse(user=request.user)
            messages.success(request, "Modification effectuée.")
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
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

        try:
            # After each successful transition, a save() is performed by django-xworkflows.
            job_application.answer = form.cleaned_data["answer"]
            job_application.postpone(user=request.user)
            messages.success(request, "Modification effectuée.")
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
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
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})

    forms = []

    # Ask the SIAE to verify the job seeker's Pôle emploi status.
    # This will ensure a smooth Approval delivery.
    form_pe_status = None
    form_user_address = None

    if job_application.to_siae.is_subject_to_eligibility_rules:
        form_pe_status = JobSeekerPoleEmploiStatusForm(instance=job_application.job_seeker, data=request.POST or None)
        forms.append(form_pe_status)

        form_user_address = UserAddressForm(instance=job_application.job_seeker, data=request.POST or None)
        forms.append(form_user_address)

    form_accept = AcceptForm(instance=job_application, data=request.POST or None)
    forms.append(form_accept)

    if request.method == "POST" and all([form.is_valid() for form in forms]):
        try:
            with transaction.atomic():
                if form_pe_status:
                    form_pe_status.save()

                if form_user_address:
                    form_user_address.save()

                # After each successful transition, a save() is performed by django-xworkflows.
                job_application = form_accept.save(commit=False)
                job_application.accept(user=request.user)
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")
            return HttpResponseRedirect(next_url)

        if job_application.to_siae.is_subject_to_eligibility_rules:
            if job_application.approval:
                PRO_CONTRACT_URL = (
                    "https://www.pole-emploi.fr/employeur/aides-aux-recrutements/"
                    "les-aides-a-lembauche/insertion-par-lactivite-economiq.html"
                )
                messages.success(
                    request,
                    mark_safe(
                        (
                            "Embauche acceptée ! "
                            "(Pour un contrat de professionnalisation vous pouvez soit introduire une "
                            "demande d’aide au poste ou demander l’aide spécifique de Pôle emploi "
                            f'<a href="{PRO_CONTRACT_URL}" rel="noopener" target="_blank">'
                            "ici"
                            "</a>)."
                        )
                    ),
                )
                messages.success(
                    request,
                    (
                        "Le numéro de PASS IAE peut être utilisé pour la déclaration "
                        "de la personne dans l'extranet IAE 2.0 de l'ASP."
                    ),
                )
            elif not job_application.hiring_without_approval:
                link = settings.ITOU_DOC_PASS_VERIFICATION_URL
                messages.success(
                    request,
                    mark_safe(
                        (
                            "Votre demande de Pass IAE est en cours de vérification auprès de nos équipes.<br>"
                            "Si vous souhaitez en savoir plus sur le processus de vérification, n’hésitez pas à "
                            "<a href='" + link + "'>consulter notre espace documentation</a>."
                        )
                    ),
                )

        messages.warning(
            request,
            mark_safe(
                "Êtes-vous satisfait des emplois de l'inclusion ? "
                + f"<a href='{settings.ITOU_EMAIL_APPROVAL_SURVEY_URL}' rel='noopener' target='_blank'>"
                + "Je donne mon avis"
                + "</a>"
            ),
        )

        return HttpResponseRedirect(next_url)

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "form_accept": form_accept,
        "form_user_address": form_user_address,
        "form_pe_status": form_pe_status,
        "job_application": job_application,
    }
    return render(request, template_name, context)


@login_required
def cancel(request, job_application_id, template_name="apply/process_cancel.html"):
    """
    Trigger the `cancel` transition.
    """
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    approvals_wrapper = job_application.job_seeker.approvals_wrapper
    check_waiting_period(approvals_wrapper, job_application)
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})

    if not job_application.can_be_cancelled:
        messages.error(request, "Vous ne pouvez pas annuler cette embauche.")
        return HttpResponseRedirect(next_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        try:
            # After each successful transition, a save() is performed by django-xworkflows.
            job_application.cancel(user=request.user)
            messages.success(request, "L'embauche a bien été annulée.")
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")
        return HttpResponseRedirect(next_url)

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "job_application": job_application,
    }
    return render(request, template_name, context)


@require_http_methods(["POST"])
@login_required
def archive(request, job_application_id):
    """
    Archive the job_application for an SIAE (ie. sets the hidden_for_siae flag to True)
    then redirects to the list of job_applications
    """
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    cancelled_states = [
        JobApplicationWorkflow.STATE_REFUSED,
        JobApplicationWorkflow.STATE_CANCELLED,
        JobApplicationWorkflow.STATE_OBSOLETE,
    ]

    args = {"states": [c for c in cancelled_states]}
    qs = urlencode(args, doseq=True)
    url = reverse("apply:list_for_siae")
    next_url = f"{url}?{qs}"

    if not job_application.can_be_archived:
        messages.error(request, "Vous ne pouvez pas supprimer cette candidature.")
        return HttpResponseRedirect(next_url)

    if request.method == "POST":
        try:
            username = f"{job_application.job_seeker.first_name} {job_application.job_seeker.last_name}"
            siae_name = job_application.to_siae.display_name

            job_application.hidden_for_siae = True
            job_application.save()

            success_message = f"La candidature de {username} chez {siae_name} a bien été supprimée."
            messages.success(request, success_message)
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")

    return HttpResponseRedirect(next_url)


@login_required
def eligibility(request, job_application_id, template_name="apply/process_eligibility.html"):
    """
    Check eligibility (as an SIAE).
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(
        queryset,
        id=job_application_id,
        state__in=[JobApplicationWorkflow.STATE_PROCESSING, JobApplicationWorkflow.STATE_POSTPONED],
    )

    if not job_application.to_siae.is_subject_to_eligibility_rules:
        raise Http404()

    form_administrative_criteria = AdministrativeCriteriaForm(
        request.user, siae=job_application.to_siae, data=request.POST or None
    )
    form_confirm_eligibility = ConfirmEligibilityForm(data=request.POST or None)

    if request.method == "POST" and form_confirm_eligibility.is_valid() and form_administrative_criteria.is_valid():
        user_info = get_user_info(request)
        EligibilityDiagnosis.create_diagnosis(
            job_application.job_seeker, user_info, administrative_criteria=form_administrative_criteria.cleaned_data
        )
        messages.success(request, "Éligibilité confirmée !")
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        return HttpResponseRedirect(next_url)

    context = {
        "approvals_wrapper": job_application.job_seeker.approvals_wrapper,
        "job_application": job_application,
        "form_administrative_criteria": form_administrative_criteria,
        "form_confirm_eligibility": form_confirm_eligibility,
    }
    return render(request, template_name, context)


@login_required
def accept_without_approval(request, job_application_id):
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    if not job_application.approval_not_needed:
        job_application.approval_not_needed = True
        job_application.save()

    return accept(request, job_application_id)
