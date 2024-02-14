import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template import loader
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST
from django.views.generic.base import TemplateView
from django_xworkflows import models as xwf_models

from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.utils.perms.prescriber import get_all_available_job_applications_as_prescriber
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import AcceptForm, AnswerForm, PriorActionForm, RefusalForm
from itou.www.apply.views import common as common_views, constants as apply_view_constants


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
        siae=job_application.to_company,
        sender_prescriber_organization=job_application.sender_prescriber_organization,
    ):
        raise PermissionDenied(apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY)


def _get_geiq_eligibility_diagnosis_for_siae(job_application):
    # Get current GEIQ diagnosis or *last expired one*
    return (
        job_application.geiq_eligibility_diagnosis
        or GEIQEligibilityDiagnosis.objects.diagnoses_for(
            job_application.job_seeker, job_application.to_company
        ).first()
    )


@login_required
def details_for_jobseeker(request, job_application_id, template_name="apply/process_details.html"):
    """
    Detail of an application for a JOBSEEKER
    """
    job_application = get_object_or_404(
        JobApplication.objects.select_related(
            "job_seeker__jobseeker_profile",
            "sender",
            "to_company",
            "eligibility_diagnosis__author",
            "eligibility_diagnosis__author_siae",
            "eligibility_diagnosis__author_prescriber_organization",
            "eligibility_diagnosis__job_seeker__jobseeker_profile",
        ).prefetch_related("selected_jobs"),
        id=job_application_id,
        job_seeker=request.user,
        hidden_for_company=False,
    )

    transition_logs = job_application.logs.select_related("user").all()

    expired_eligibility_diagnosis = EligibilityDiagnosis.objects.last_expired(
        job_seeker=job_application.job_seeker, for_siae=job_application.to_company
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse_lazy("apply:list_for_job_seeker"))
    geiq_eligibility_diagnosis = None

    if job_application.to_company.kind == CompanyKind.GEIQ:
        geiq_eligibility_diagnosis = _get_geiq_eligibility_diagnosis_for_siae(job_application)

    context = {
        "can_view_personal_information": request.user.can_view_personal_information(job_application.job_seeker),
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "eligibility_diagnosis": job_application.get_eligibility_diagnosis(),
        "expired_eligibility_diagnosis": expired_eligibility_diagnosis,
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "job_application": job_application,
        "transition_logs": transition_logs,
        "back_url": back_url,
        "matomo_custom_title": "Candidature",
    }

    return render(request, template_name, context)


@login_required
def details_for_company(request, job_application_id, template_name="apply/process_details_company.html"):
    """
    Detail of an application for an SIAE with the ability:
    - to update start date of a contract (provided given date is in the future),
    - to give an answer.
    """
    queryset = (
        JobApplication.objects.is_active_company_member(request.user)
        .not_archived()
        .select_related(
            "job_seeker__jobseeker_profile",
            "eligibility_diagnosis__author",
            "eligibility_diagnosis__job_seeker__jobseeker_profile",
            "eligibility_diagnosis__author_siae",
            "eligibility_diagnosis__author_prescriber_organization",
            "geiq_eligibility_diagnosis",
            "sender",
            "sender_company",
            "sender_prescriber_organization",
            "to_company",
            "approval",
        )
        .prefetch_related("selected_jobs__appellation")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = job_application.logs.select_related("user").all()

    expired_eligibility_diagnosis = EligibilityDiagnosis.objects.last_expired(
        job_seeker=job_application.job_seeker, for_siae=job_application.to_company
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse_lazy("apply:list_for_siae"))
    geiq_eligibility_diagnosis = None

    if job_application.to_company.kind == CompanyKind.GEIQ:
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
@user_passes_test(lambda u: u.is_prescriber, login_url=reverse_lazy("search:employers_home"), redirect_field_name=None)
def details_for_prescriber(request, job_application_id, template_name="apply/process_details.html"):
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
        "sender_company",
        "sender_prescriber_organization",
        "to_company",
        "approval",
    ).prefetch_related("selected_jobs__appellation")
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = job_application.logs.select_related("user").all()

    # We are looking for the most plausible availability date for eligibility criterions
    before_date = job_application.hiring_end_at

    if before_date is None and job_application.approval and job_application.approval.end_at is not None:
        before_date = job_application.approval.end_at
    else:
        before_date = datetime.datetime.now()

    back_url = get_safe_url(request, "back_url", fallback_url=reverse_lazy("apply:list_for_prescriber"))

    # Latest GEIQ diagnosis for this job seeker created by a *prescriber*
    geiq_eligibility_diagnosis = (
        job_application.to_company.kind == CompanyKind.GEIQ
        and GEIQEligibilityDiagnosis.objects.valid()
        .filter(author_prescriber_organization__isnull=False)
        .for_job_seeker(job_application.job_seeker)
        .select_related("author", "author_geiq", "author_prescriber_organization")
        .first()
    )

    # Refused applications information is providen to prescribers
    if display_refusal_info := job_application.is_refused_for_other_reason:
        refused_by = job_application.refused_by
        refusal_contact_email = refused_by.email if refused_by else job_application.to_company.email
    else:
        refused_by = None
        refusal_contact_email = ""

    context = {
        "can_view_personal_information": request.user.can_view_personal_information(job_application.job_seeker),
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "eligibility_diagnosis": job_application.get_eligibility_diagnosis(),
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "job_application": job_application,
        "transition_logs": transition_logs,
        "back_url": back_url,
        "matomo_custom_title": "Candidature",
        "display_refusal_info": display_refusal_info,
        "refused_by": refused_by,
        "refusal_contact_email": refusal_contact_email,
    }

    return render(request, template_name, context)


@login_required
@require_POST
def process(request, job_application_id):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    try:
        # After each successful transition, a save() is performed by django-xworkflows.
        job_application.process(user=request.user)
    except xwf_models.InvalidTransitionError:
        messages.error(request, "Action déjà effectuée.")

    next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
    return HttpResponseRedirect(next_url)


@login_required
def refuse(request, job_application_id, template_name="apply/process_refuse.html"):
    queryset = JobApplication.objects.is_active_company_member(request.user)
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

        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
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
    queryset = JobApplication.objects.is_active_company_member(request.user)
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

        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
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
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)
    check_waiting_period(job_application)
    next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    if not job_application.hiring_without_approval and job_application.eligibility_diagnosis_by_siae_required:
        messages.error(request, "Cette candidature requiert un diagnostic d'éligibilité pour être acceptée.")
        return HttpResponseRedirect(next_url)

    return common_views._accept(
        request,
        job_application.to_company,
        job_application.job_seeker,
        error_url=next_url,
        back_url=next_url,
        template_name=template_name,
        extra_context={},
        job_application=job_application,
    )


class AcceptHTMXFragmentView(TemplateView):
    NO_ERROR_FIELDS = []

    def setup(self, request, job_application_id=None, company_pk=None, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if company_pk is not None:
            company = get_object_or_404(Company.objects.member_required(request.user), pk=company_pk)
            job_application = None
        elif job_application_id:
            # TODO(xfernandez): remove this version in a week
            queryset = JobApplication.objects.is_active_company_member(request.user)
            job_application = get_object_or_404(queryset, id=job_application_id)
            company = job_application.to_company
        self.form_accept = AcceptForm(instance=job_application, company=company, data=request.POST or None)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form_accept": self.form_accept,
            "hide_value": ContractType.OTHER.value,
        }

    def post(self, request, *args, **kwargs):
        # we don't want to display error on this field for an HTMX reload:
        for field_name in self.NO_ERROR_FIELDS:
            if field_name in self.form_accept.errors.keys():
                self.form_accept.errors.pop(field_name)

        return self.render_to_response(self.get_context_data(**kwargs))


class ReloadQualificationFields(AcceptHTMXFragmentView):
    template_name = "apply/includes/geiq/geiq_qualification_fields.html"
    NO_ERROR_FIELDS = ("qualification_level",)


class ReloadContractTypeAndOptions(AcceptHTMXFragmentView):
    template_name = "apply/includes/geiq/geiq_contract_type_and_options.html"
    NO_ERROR_FIELDS = ("contract_type_details", "nb_hours_per_week")


class ReloadJobDescriptionFields(AcceptHTMXFragmentView):
    template_name = "apply/includes/job_description_fields.html"
    NO_ERROR_FIELDS = ("appellation", "location")


@login_required
def cancel(request, job_application_id, template_name="apply/process_cancel.html"):
    """
    Trigger the `cancel` transition.
    """
    queryset = JobApplication.objects.is_active_company_member(request.user).select_related("to_company")
    job_application = get_object_or_404(queryset, id=job_application_id)
    check_waiting_period(job_application)
    next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})

    if not job_application.can_be_cancelled:
        messages.error(request, "Vous ne pouvez pas annuler cette embauche.")
        return HttpResponseRedirect(next_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        try:
            # After each successful transition, a save() is performed by django-xworkflows.
            job_application.cancel(user=request.user)
            messages.success(request, "L'embauche a bien été annulée.", extra_tags="toast")
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
    Archive the job_application for an SIAE (ie. sets the hidden_for_company flag to True)
    then redirects to the list of job_applications
    """
    queryset = JobApplication.objects.is_active_company_member(request.user)
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
            username = job_application.job_seeker.get_full_name()
            siae_name = job_application.to_company.display_name

            job_application.hidden_for_company = True
            job_application.save()

            success_message = f"La candidature de {username} chez {siae_name} a bien été supprimée."
            messages.success(request, success_message)
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")

    return HttpResponseRedirect(next_url)


@login_required
def transfer(request, job_application_id):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, pk=job_application_id)
    target_company = get_object_or_404(Company.objects, pk=request.POST.get("target_company_id"))
    back_url = request.POST.get("back_url", reverse("apply:list_for_siae"))

    try:
        job_application.transfer_to(request.user, target_company)
        messages.success(
            request,
            (
                f"La candidature de {job_application.job_seeker.get_full_name()} "
                f"a bien été transférée à {target_company.display_name}||"
                "Pour la consulter, rendez-vous sur son tableau de bord en changeant de structure"
            ),
            extra_tags="toast",
        )
    except Exception as ex:
        messages.error(
            request,
            "Une erreur est survenue lors du transfert de la candidature : "
            f"{ job_application= }, { target_company= }, { ex= }",
        )

    return HttpResponseRedirect(back_url)


@login_required
@require_POST
def send_diagoriente_invite(request, job_application_id):
    """
    As a company member, I can send a Diagoriente invite to the prescriber or the job seeker.
    """
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset.select_for_update(), pk=job_application_id)
    if not job_application.resume_link and not job_application.diagoriente_invite_sent_at:
        if job_application.is_sent_by_proxy:
            job_application.email_diagoriente_invite_for_prescriber.send()
        else:
            job_application.email_diagoriente_invite_for_job_seeker.send()
        job_application.diagoriente_invite_sent_at = timezone.now()
        job_application.save(update_fields=["diagoriente_invite_sent_at"])
        messages.success(request, "L'invitation à utiliser Diagoriente a été envoyée.")

    redirect_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application_id})
    return HttpResponseRedirect(redirect_url)


@login_required
def eligibility(request, job_application_id, template_name="apply/process_eligibility.html"):
    """
    Check eligibility (as an SIAE).
    """

    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(
        queryset,
        id=job_application_id,
        state__in=JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES,
    )
    return common_views._eligibility(
        request,
        job_application.to_company,
        job_application.job_seeker,
        cancel_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id}),
        next_url=reverse("apply:accept", kwargs={"job_application_id": job_application.id}),
        template_name=template_name,
        extra_context={"job_application": job_application},
    )


@login_required
def geiq_eligibility(request, job_application_id, template_name="apply/process_geiq_eligibility.html"):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    # Check GEIQ eligibility during job application process
    job_application = get_object_or_404(queryset, pk=job_application_id)
    back_url = request.GET.get("back_url") or reverse(
        "apply:details_for_company", kwargs={"job_application_id": job_application.pk}
    )
    next_url = request.GET.get("next_url")
    return common_views._geiq_eligibility(
        request,
        job_application.to_company,
        job_application.job_seeker,
        back_url=back_url,
        next_url=next_url,
        geiq_eligibility_criteria_url=reverse(
            "apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk}
        ),
        template_name=template_name,
        extra_context={},
    )


@login_required
def geiq_eligibility_criteria(
    request,
    job_application_id,
    template_name="apply/includes/geiq/check_geiq_eligibility_form.html",
):
    """Dynamic GEIQ eligibility criteria form (HTMX)"""

    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, pk=job_application_id)
    return common_views._geiq_eligibility_criteria(request, job_application.to_company, job_application.job_seeker)


@require_POST
def delete_prior_action(request, job_application_id, prior_action_id):
    queryset = JobApplication.objects.is_active_company_member(request.user)
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
                "transition_logs": job_application.logs.select_related("user").all(),
                "geiq_eligibility_diagnosis": (
                    _get_geiq_eligibility_diagnosis_for_siae(job_application)
                    if job_application.to_company.kind == CompanyKind.GEIQ
                    else None
                ),
            },
            request=request,
        )
        if state_changed
        else ""
    )
    return HttpResponse(content)


@login_required
def add_or_modify_prior_action(request, job_application_id, prior_action_id=None):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(
        queryset,
        id=job_application_id,
    )
    if not job_application.can_change_prior_actions:
        return HttpResponseForbidden()

    prior_action = (
        get_object_or_404(
            PriorAction.objects.filter(job_application=job_application),
            pk=prior_action_id,
        )
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
            if state_update and job_application.to_company.kind == CompanyKind.GEIQ:
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
                    "transition_logs": job_application.logs.select_related("user").all() if state_update else None,
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
                kwargs={
                    "job_application_id": job_application.pk,
                    "prior_action_id": prior_action.pk,
                },
            )
            if prior_action
            else reverse(
                "apply:add_prior_action",
                kwargs={"job_application_id": job_application.pk},
            )
        ),
        # When editing existing action, we want to keep the hr from job_application_prior_action.html
        "final_hr": prior_action is not None,
    }
    return render(request, "apply/includes/job_application_prior_action_form.html", context)
