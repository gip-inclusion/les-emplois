import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template import loader
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django_htmx.http import HttpResponseClientRedirect
from django_xworkflows import models as xwf_models

from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.utils import geiq_allowance_amount
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.siaes.enums import ContractType, SiaeKind
from itou.siaes.models import Siae
from itou.users.models import ApprovalAlreadyExistsError
from itou.utils import constants as global_constants
from itou.utils.htmx import hx_trigger_modal_control
from itou.utils.perms.prescriber import get_all_available_job_applications_as_prescriber
from itou.utils.perms.user import get_user_info
from itou.utils.urls import get_external_link_markup, get_safe_url
from itou.www.apply.forms import (
    AcceptForm,
    AnswerForm,
    CheckJobSeekerGEIQEligibilityForm,
    JobSeekerPersonalDataForm,
    PriorActionForm,
    RefusalForm,
    UserAddressForm,
)
from itou.www.apply.views import constants as apply_view_constants
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForGEIQForm


def check_waiting_period(job_application):
    """
    This should be an edge case.
    An approval may expire between the time an application is sent and
    the time it is accepted.
    """
    # NOTE(vperron): We need to check both PASS and PE Approvals for ongoing eligibility issues.
    # This code should still stay relevant for the 3.5 years to come to account for the PE approvals
    # that have been delivered in December 2021 (and that may have 2 years waiting periods)
    if job_application.job_seeker.approval_can_be_renewed_by(
        siae=job_application.to_siae, sender_prescriber_organization=job_application.sender_prescriber_organization
    ):
        raise PermissionDenied(apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY)


def _get_geiq_eligibility_diagnosis_for_siae(job_application):
    # Get current GEIQ diagnosis or *last expired one*
    return (
        job_application.geiq_eligibility_diagnosis
        or GEIQEligibilityDiagnosis.objects.diagnoses_for(job_application.job_seeker, job_application.to_siae).first()
    )


@login_required
def details_for_siae(request, job_application_id, template_name="apply/process_details_siae.html"):
    """
    Detail of an application for an SIAE with the ability:
    - to update start date of a contract (provided given date is in the future),
    - to give an answer.
    """
    queryset = (
        JobApplication.objects.siae_member_required(request.user)
        .not_archived()
        .select_related(
            "job_seeker",
            "eligibility_diagnosis",
            "geiq_eligibility_diagnosis",
            "sender",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae",
            "approval",
        )
        .prefetch_related("selected_jobs__appellation")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = job_application.logs.select_related("user").all().order_by("timestamp")

    expired_eligibility_diagnosis = EligibilityDiagnosis.objects.last_expired(
        job_seeker=job_application.job_seeker, for_siae=job_application.to_siae
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse_lazy("apply:list_for_siae"))
    geiq_eligibility_diagnosis = None

    if job_application.to_siae.kind == SiaeKind.GEIQ:
        geiq_eligibility_diagnosis = _get_geiq_eligibility_diagnosis_for_siae(job_application)

    context = {
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "eligibility_diagnosis": job_application.get_eligibility_diagnosis(),
        "expired_eligibility_diagnosis": expired_eligibility_diagnosis,
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "job_application": job_application,
        "transition_logs": transition_logs,
        "back_url": back_url,
        "add_prior_action_form": (
            PriorActionForm(action_only=True) if job_application.can_change_prior_actions else None
        ),
        "matomo_custom_title": "Candidature",
    }

    return render(request, template_name, context)


@login_required
@user_passes_test(lambda u: u.is_prescriber, login_url="/", redirect_field_name=None)
def details_for_prescriber(request, job_application_id, template_name="apply/process_details_prescriber.html"):
    """
    Detail of an application for an SIAE with the ability:
    - to update start date of a contract (provided given date is in the future),
    - to give an answer.
    """
    job_applications = get_all_available_job_applications_as_prescriber(request)

    queryset = job_applications.select_related(
        "job_seeker",
        "eligibility_diagnosis",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
        "approval",
    ).prefetch_related("selected_jobs__appellation")
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = job_application.logs.select_related("user").all().order_by("timestamp")

    # We are looking for the most plausible availability date for eligibility criterions
    before_date = job_application.hiring_end_at

    if before_date is None and job_application.approval and job_application.approval.end_at is not None:
        before_date = job_application.approval.end_at
    else:
        before_date = datetime.datetime.now()

    back_url = get_safe_url(request, "back_url", fallback_url=reverse_lazy("apply:list_for_prescriber"))

    # Latest GEIQ diagnosis for this job seeker created by a *prescriber*
    geiq_eligibility_diagnosis = (
        job_application.to_siae.kind == SiaeKind.GEIQ
        and GEIQEligibilityDiagnosis.objects.valid()
        .filter(author_prescriber_organization__isnull=False)
        .for_job_seeker(job_application.job_seeker)
        .first()
    )

    context = {
        "can_view_personal_information": request.user.can_view_personal_information(job_application.job_seeker),
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "eligibility_diagnosis": job_application.get_eligibility_diagnosis(),
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "job_application": job_application,
        "transition_logs": transition_logs,
        "back_url": back_url,
        "matomo_custom_title": "Candidature",
    }

    return render(request, template_name, context)


@login_required
@require_POST
def process(request, job_application_id):
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
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    form = RefusalForm(job_application=job_application, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            # After each successful transition, a save() is performed by django-xworkflows.
            job_application.refusal_reason = form.cleaned_data["refusal_reason"]
            job_application.answer = form.cleaned_data["answer"]
            job_application.answer_to_prescriber = form.cleaned_data.get("answer_to_prescriber", "")
            job_application.refuse(user=request.user)
            messages.success(request, "Modification effectuée.")
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        return HttpResponseRedirect(next_url)
    context = {
        "form": form,
        "job_application": job_application,
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "matomo_custom_title": "Candidature refusée",
    }
    return render(request, template_name, context)


@login_required
def postpone(request, job_application_id, template_name="apply/process_postpone.html"):
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    check_waiting_period(job_application)

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
        "form": form,
        "job_application": job_application,
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "matomo_custom_title": "Candidature différée",
    }
    return render(request, template_name, context)


@login_required
def accept(request, job_application_id, template_name="apply/process_accept.html"):
    """
    Trigger the `accept` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    check_waiting_period(job_application)
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})

    forms = []

    # Ask the SIAE to verify the job seeker's Pôle emploi status.
    # This will ensure a smooth Approval delivery.
    form_personal_data = None
    form_user_address = None

    if job_application.to_siae.is_subject_to_eligibility_rules:
        # Info that will be used to search for an existing Pôle emploi approval.
        form_personal_data = JobSeekerPersonalDataForm(
            instance=job_application.job_seeker,
            data=request.POST or None,
            tally_form_query=f"jobapplication={job_application.pk}",
        )
        forms.append(form_personal_data)

        form_user_address = UserAddressForm(instance=job_application.job_seeker, data=request.POST or None)
        forms.append(form_user_address)

    form_accept = AcceptForm(instance=job_application, data=request.POST or None)
    forms.append(form_accept)

    context = {
        "form_accept": form_accept,
        "form_user_address": form_user_address,
        "form_personal_data": form_personal_data,
        "job_application": job_application,
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "hide_value": ContractType.OTHER.value,
        "matomo_custom_title": "Candidature acceptée",
    }

    if not job_application.hiring_without_approval and job_application.eligibility_diagnosis_by_siae_required:
        messages.error(request, "Cette candidature requiert un diagnostic d'éligibilité pour être acceptée.")
        return HttpResponseRedirect(next_url)

    if request.method == "POST" and all([form.is_valid() for form in forms]):

        if request.htmx and not request.POST.get("confirmed"):
            return TemplateResponse(
                request=request,
                template=template_name,
                context=context,
                headers=hx_trigger_modal_control("js-confirmation-modal", "show"),
            )

        try:
            with transaction.atomic():
                if form_personal_data:
                    form_personal_data.save()
                if form_user_address:
                    form_user_address.save()
                # After each successful transition, a save() is performed by django-xworkflows,
                # so use `commit=False` to avoid a double save.
                job_application = form_accept.save(commit=False)
                job_application.accept(user=request.user)

                # Mark job seeker's infos as up-to-date
                job_application.job_seeker.last_checked_at = timezone.now()
                job_application.job_seeker.save(update_fields=["last_checked_at"])
        except ApprovalAlreadyExistsError:
            link_to_form = get_external_link_markup(
                url=f"{global_constants.ITOU_COMMUNITY_URL }/aide/emplois/#support",
                text="ce formulaire",
            )
            messages.error(
                request,
                # NOTE(vperron): maybe a small template would be better if this gets more complex.
                mark_safe(
                    "Ce candidat semble avoir plusieurs comptes sur Les emplois de l'inclusion "
                    "(même identifiant Pôle emploi mais adresse e-mail différente). "
                    "<br>"
                    "Un PASS IAE lui a déjà été délivré mais il est associé à un autre compte. "
                    "<br>"
                    f"Pour que nous régularisions la situation, merci de remplir {link_to_form} en nous indiquant : "
                    "<ul>"
                    "<li> nom et prénom du salarié"
                    "<li> numéro de sécurité sociale"
                    "<li> sa date de naissance"
                    "<li> son identifiant Pôle Emploi"
                    "<li> la référence d’un agrément Pôle Emploi ou d’un PASS IAE lui appartenant (si vous l’avez) "
                    "</ul>"
                ),
            )
            return HttpResponseClientRedirect(next_url)
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")
            return HttpResponseClientRedirect(next_url)

        if job_application.to_siae.is_subject_to_eligibility_rules:
            # Automatic approval delivery mode.
            if job_application.approval:
                external_link = get_external_link_markup(
                    url=(
                        "https://www.pole-emploi.fr/employeur/aides-aux-recrutements/"
                        "les-aides-a-lembauche/insertion-par-lactivite-economiq.html"
                    ),
                    text="l’aide spécifique de Pôle emploi",
                )
                messages.success(
                    request,
                    mark_safe(
                        "Embauche acceptée ! Pour un contrat de professionnalisation, vous pouvez "
                        f"demander l'aide au poste ou {external_link}."
                    ),
                )
                messages.success(
                    request,
                    (
                        "Le numéro de PASS IAE peut être utilisé pour la déclaration "
                        "de la personne dans l'extranet IAE 2.0 de l'ASP."
                    ),
                )
            # Manual approval delivery mode.
            elif not job_application.hiring_without_approval:
                external_link = get_external_link_markup(
                    url=(
                        f"{global_constants.ITOU_COMMUNITY_URL }/doc/emplois/pass-iae-comment-ca-marche/"
                        "#verification-des-demandes-de-pass-iae"
                    ),
                    text="consulter notre espace documentation",
                )
                messages.success(
                    request,
                    mark_safe(
                        "Votre demande de PASS IAE est en cours de vérification auprès de nos équipes.<br>"
                        "Si vous souhaitez en savoir plus sur le processus de vérification, n’hésitez pas à "
                        f"{external_link}."
                    ),
                )
        elif job_application.to_siae.kind == SiaeKind.GEIQ:
            # If job seeker has as valid GEIQ diagnosis issued by a GEIQ or a prescriber
            # link this diagnosis to the current job application
            if geiq_eligibility_diagnosis := GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                job_application.job_seeker, job_application.to_siae
            ).first():
                job_application.geiq_eligibility_diagnosis = geiq_eligibility_diagnosis
                job_application.save(update_fields=["geiq_eligibility_diagnosis"])

        external_link = get_external_link_markup(
            url=job_application.to_siae.accept_survey_url,
            text="Je donne mon avis",
        )
        messages.warning(
            request,
            mark_safe(f"Êtes-vous satisfait des emplois de l'inclusion ? {external_link}"),
        )

        return HttpResponseClientRedirect(next_url)

    return render(request, template_name, {**context, "has_form_error": any(form.errors for form in forms)})


def reload_qualification_fields(
    request, job_application_id, template_name="apply/includes/geiq/geiq_qualification_fields.html"
):
    # This is an HTMX part
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    form_accept = AcceptForm(instance=job_application, data=request.POST or None)
    ctx = {
        "form_accept": form_accept,
        "job_application": job_application,
    }
    return render(request, template_name, ctx)


@login_required
def cancel(request, job_application_id, template_name="apply/process_cancel.html"):
    """
    Trigger the `cancel` transition.
    """
    queryset = JobApplication.objects.siae_member_required(request.user).select_related("to_siae")
    job_application = get_object_or_404(queryset, id=job_application_id)
    check_waiting_period(job_application)
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})

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
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "job_application": job_application,
        "matomo_custom_title": "Candidature annulée",
    }
    return render(request, template_name, context)


@require_POST
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

    qs = urlencode({"states": cancelled_states}, doseq=True)
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
def transfer(request, job_application_id):
    job_application = get_object_or_404(JobApplication.objects, pk=job_application_id)
    target_siae = get_object_or_404(Siae.objects, pk=request.POST.get("target_siae_id"))
    back_url = request.POST.get("back_url", reverse("apply:list_for_siae"))

    try:
        job_application.transfer_to(request.user, target_siae)
        messages.success(
            request,
            mark_safe(
                f"<p>La candidature de <b>{ job_application.job_seeker.first_name }"
                f" { job_application.job_seeker.last_name }</b>"
                f" a bien été transférée à la SIAE <b>{ target_siae.display_name }</b>,"
                f" { target_siae.address_on_one_line }.</p>"
                "<p>Pour la consulter, rendez-vous sur son tableau de bord en changeant de structure.</p>",
            ),
        )
    except Exception as ex:
        messages.error(
            request,
            "Une erreur est survenue lors du transfert de la candidature : "
            f"{ job_application= }, { target_siae= }, { ex= }",
        )

    return HttpResponseRedirect(back_url)


@login_required
def eligibility(request, job_application_id, template_name="apply/process_eligibility.html"):
    """
    Check eligibility (as an SIAE).
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(
        queryset,
        id=job_application_id,
        state__in=JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES,
    )

    if not job_application.to_siae.is_subject_to_eligibility_rules:
        raise Http404()

    if suspension_explanation := job_application.to_siae.get_active_suspension_text_with_dates():
        raise PermissionDenied(
            "Vous ne pouvez pas valider les critères d'éligibilité suite aux mesures prises dans le cadre "
            "du contrôle a posteriori. " + suspension_explanation
        )

    form_administrative_criteria = AdministrativeCriteriaForm(
        request.user, siae=job_application.to_siae, data=request.POST or None
    )
    if request.method == "POST" and form_administrative_criteria.is_valid():
        user_info = get_user_info(request)
        EligibilityDiagnosis.create_diagnosis(
            job_application.job_seeker, user_info, administrative_criteria=form_administrative_criteria.cleaned_data
        )
        messages.success(request, "Éligibilité confirmée !")
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        return HttpResponseRedirect(next_url)

    context = {
        "job_application": job_application,
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "form_administrative_criteria": form_administrative_criteria,
        "job_seeker": job_application.job_seeker,
        "matomo_custom_title": "Evaluation de la candidature",
    }
    return render(request, template_name, context)


@login_required
def geiq_eligibility(request, job_application_id, template_name="apply/process_geiq_eligibility.html"):
    # Check GEIQ eligibility during job application process
    job_application = get_object_or_404(JobApplication, pk=job_application_id)
    back_url = request.GET.get("back_url") or reverse(
        "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
    )
    next_url = request.GET.get("next_url")
    form = CheckJobSeekerGEIQEligibilityForm(job_application, back_url, next_url, data=request.POST or None)

    if request.method == "POST" and form.is_valid() and request.htmx:
        if form.cleaned_data["choice"]:
            return HttpResponseRedirect(
                reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})
            )
        else:
            return HttpResponseRedirect(
                reverse("apply:continue_without_geiq_diagnosis", kwargs={"job_application_id": job_application.pk})
                + f"?next_url={request.session.get('next_url')}"
            )

    navigation = {"next_url": next_url, "back_url": back_url}

    request.session.update(navigation)

    context = {
        "progress": 33,
        "can_view_personal_information": True,
        "job_application": job_application,
        "job_seeker": job_application.job_seeker,
        "form": form,
    } | navigation

    return render(request, template_name, context)


# HTMX fragments


@login_required
def continue_without_geiq_diagnosis(
    request, job_application_id, template_name="apply/includes/geiq/continue_without_geiq_diagnosis_form.html"
):
    job_application = get_object_or_404(JobApplication, pk=job_application_id)
    next_url = request.session.get("next_url")

    if request.method == "POST":
        del request.session["next_url"]
        return HttpResponseRedirect(next_url)

    context = {
        "job_application": job_application,
        "next_url": next_url,
        "progress": 66,
    }

    return render(request, template_name, context)


@login_required
def geiq_eligibility_criteria(
    request, job_application_id, template_name="apply/includes/geiq/check_geiq_eligibility_form.html"
):
    """Dynamic GEIQ eligibility criteria form (HTMX)"""

    job_application = get_object_or_404(JobApplication, pk=job_application_id)
    diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
        job_application.job_seeker, job_application.to_siae
    ).first()
    form = GEIQAdministrativeCriteriaForGEIQForm(
        job_application.to_siae,
        diagnosis.administrative_criteria.all() if diagnosis else [],
        request.path,
        data=request.POST or None,
    )
    next_url = request.session.get("next_url")
    allowance_amount = None

    if request.method == "POST" and form.is_valid():
        criteria = form.cleaned_data
        if request.htmx:
            allowance_amount = geiq_allowance_amount(request.user.is_prescriber_with_authorized_org, criteria)
        else:
            if diagnosis:
                GEIQEligibilityDiagnosis.update_eligibility_diagnosis(diagnosis, request.user, criteria)
            else:
                GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
                    job_application.job_seeker, request.user, job_application.to_siae, criteria
                )

            del request.session["back_url"]
            del request.session["next_url"]

            return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "allowance_amount": allowance_amount,
        "progress": 66,
    }

    if job_application.job_seeker.address_in_qpv or job_application.job_seeker.zrr_city_name:
        context |= {"geo_criteria_detected": True, "job_seeker": job_application.job_seeker}

    return render(request, template_name, context)


@require_POST
def delete_prior_action(request, job_application_id, prior_action_id):
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(
        queryset,
        id=job_application_id,
    )
    if not job_application.can_change_prior_actions:
        return HttpResponseForbidden()

    prior_action = get_object_or_404(PriorAction.objects.filter(job_application=job_application), pk=prior_action_id)

    state_changed = False
    prior_action.delete()
    if job_application.state.is_prior_to_hire and not job_application.prior_actions.exists():
        job_application.cancel_prior_to_hire(user=request.user)
        state_changed = True

    content = (
        loader.render_to_string(
            "apply/includes/out_of_band_changes_on_job_application_state_update_siae.html",
            context={
                "job_application": job_application,
                "transition_logs": job_application.logs.select_related("user").all().order_by("timestamp"),
                "geiq_eligibility_diagnosis": (
                    _get_geiq_eligibility_diagnosis_for_siae(job_application)
                    if job_application.to_siae.kind == SiaeKind.GEIQ
                    else None
                ),
            },
            request=request,
        )
        if state_changed
        else ""
    )
    return HttpResponse(
        content, headers=hx_trigger_modal_control(f"delete_prior_action_{ prior_action_id }_modal", "hide")
    )


@login_required
def add_or_modify_prior_action(request, job_application_id, prior_action_id=None):
    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(
        queryset,
        id=job_application_id,
    )
    if not job_application.can_change_prior_actions:
        return HttpResponseForbidden()

    prior_action = (
        get_object_or_404(PriorAction.objects.filter(job_application=job_application), pk=prior_action_id)
        if prior_action_id
        else None
    )

    if prior_action and not request.POST and "modify" not in request.GET:
        # GET on prior-action/<prior_action_id/ to get readonly infos
        return render(
            request,
            "apply/includes/job_application_prior_action.html",
            {
                "job_application": job_application,
                "prior_action": prior_action,
            },
        )

    form = PriorActionForm(
        request.POST or None,
        instance=prior_action,
        # GET on /prior-action/add
        action_only=prior_action is None and request.method == "GET",
    )

    if request.POST:
        # First POST in add form, dates could not be filled
        # Do not show errors
        if prior_action is None and "start_at" not in request.POST:
            for field in ["start_at", "end_at"]:
                if field not in request.POST and field in form.errors:
                    del form.errors[field]
        elif form.is_valid():
            state_update = False
            if prior_action is None:
                form.instance.job_application = job_application
                if not job_application.state.is_prior_to_hire:
                    job_application.move_to_prior_to_hire(user=request.user)
                    state_update = True
            form.save()
            geiq_eligibility_diagnosis = None
            if state_update and job_application.to_siae.kind == SiaeKind.GEIQ:
                geiq_eligibility_diagnosis = _get_geiq_eligibility_diagnosis_for_siae(job_application)
            return render(
                request,
                "apply/includes/job_application_prior_action.html",
                {
                    "job_application": job_application,
                    "prior_action": form.instance,
                    # If we were in the "add" form, make sure to keep an other add form
                    "add_prior_action_form": PriorActionForm(action_only=True) if prior_action is None else None,
                    # If out-of-band changes are needed
                    "with_oob_state_update": state_update,
                    "transition_logs": (
                        job_application.logs.select_related("user").all().order_by("timestamp")
                        if state_update
                        else None
                    ),
                    "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
                },
            )

    context = {
        "form": form,
        "job_application": job_application,
        "main_div_id": f"prior-action-{ prior_action.pk }" if prior_action else "add_prior_action",
        "form_url": (
            reverse(
                "apply:modify_prior_action",
                kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
            )
            if prior_action
            else reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
        ),
        # When editing existing action, we want to keep the hr from job_application_prior_action.html
        "final_hr": prior_action is not None,
    }
    return render(request, "apply/includes/job_application_prior_action_form.html", context)
