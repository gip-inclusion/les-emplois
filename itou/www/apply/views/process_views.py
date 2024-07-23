import datetime
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
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
from formtools.wizard.views import NamedUrlSessionWizardView

from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    AcceptForm,
    AnswerForm,
    JobApplicationRefusalJobSeekerAnswerForm,
    JobApplicationRefusalPrescriberAnswerForm,
    JobApplicationRefusalReasonForm,
    PriorActionForm,
    TransferJobApplicationForm,
)
from itou.www.apply.views import common as common_views, constants as apply_view_constants
from itou.www.apply.views.submit_views import ApplicationEndView, ApplicationJobsView, ApplicationResumeView
from itou.www.companies_views.views import CompanyCardView, JobDescriptionCardView
from itou.www.search.views import EmployerSearchView


def check_waiting_period(job_application):
    """
    This should be an edge case.
    An approval may expire between the time an application is sent and
    the time it is accepted.
    """
    # NOTE(vperron): We need to check both PASS and PE Approvals for ongoing eligibility issues.
    # This code should still stay relevant for the 3.5 years to come to account for the PE approvals
    # that have been delivered in December 2021 (and that may have 2 years waiting periods)
    if job_application.job_seeker.new_approval_blocked_by_waiting_period(
        siae=job_application.to_company,
        sender_prescriber_organization=job_application.sender_prescriber_organization,
    ):
        raise PermissionDenied(apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY)


def _get_geiq_eligibility_diagnosis(job_application, only_prescriber):
    # Return the job_application diagnosis if it's accepted
    if job_application.state.is_accepted:
        # but not if the viewer is a prescriber and the diangosis was made by the company
        if only_prescriber and job_application.geiq_eligibility_diagnosis.author_geiq:
            return None
        return job_application.geiq_eligibility_diagnosis
    return GEIQEligibilityDiagnosis.objects.diagnoses_for(
        job_application.job_seeker,
        job_application.to_company if not only_prescriber else None,
    ).first()


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

    geiq_eligibility_diagnosis = (
        job_application.to_company.kind == CompanyKind.GEIQ
        and _get_geiq_eligibility_diagnosis(job_application, only_prescriber=False)
    )

    context = {
        "can_view_personal_information": request.user.can_view_personal_information(job_application.job_seeker),
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "display_refusal_info": False,
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

    geiq_eligibility_diagnosis = (
        job_application.to_company.kind == CompanyKind.GEIQ
        and _get_geiq_eligibility_diagnosis(job_application, only_prescriber=False)
    )

    context = {
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "display_refusal_info": False,
        "eligibility_diagnosis": job_application.get_eligibility_diagnosis(),
        "eligibility_diagnosis_by_siae_required": job_application.eligibility_diagnosis_by_siae_required(),
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
@user_passes_test(
    lambda u: u.is_prescriber or u.is_employer,
    login_url=reverse_lazy("search:employers_home"),
    redirect_field_name=None,
)
def details_for_prescriber(request, job_application_id, template_name="apply/process_details.html"):
    """
    Detail of an application for an SIAE with the ability:
    - to update start date of a contract (provided given date is in the future),
    - to give an answer.
    """
    job_applications = JobApplication.objects.prescriptions_of(request.user, request.current_organization)

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

    back_url = get_safe_url(request, "back_url", fallback_url=reverse_lazy("apply:list_prescriptions"))

    # Latest GEIQ diagnosis for this job seeker created by a *prescriber*
    geiq_eligibility_diagnosis = (
        job_application.to_company.kind == CompanyKind.GEIQ
        and _get_geiq_eligibility_diagnosis(job_application, only_prescriber=True)
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


def _show_prescriber_answer_form(wizard):
    return wizard.job_application.sender_kind == job_applications_enums.SenderKind.PRESCRIBER


class JobApplicationRefuseView(LoginRequiredMixin, NamedUrlSessionWizardView):
    STEP_REASON = "reason"
    STEP_JOB_SEEKER_ANSWER = "job-seeker-answer"
    STEP_PRESCRIBER_ANSWER = "prescriber-answer"

    template_name = "apply/process_refuse.html"
    form_list = [
        (STEP_REASON, JobApplicationRefusalReasonForm),
        (STEP_JOB_SEEKER_ANSWER, JobApplicationRefusalJobSeekerAnswerForm),
        (STEP_PRESCRIBER_ANSWER, JobApplicationRefusalPrescriberAnswerForm),
    ]
    condition_dict = {
        STEP_PRESCRIBER_ANSWER: _show_prescriber_answer_form,
    }

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user).select_related("job_seeker"),
                pk=kwargs["job_application_id"],
            )

    def check_wizard_state(self, *args, **kwargs):
        # Redirect to job application details if the state is not refusable
        if self.job_application.state not in JobApplicationWorkflow.CAN_BE_REFUSED_STATES:
            message = "Action déjà effectuée." if self.job_application.state.is_refused else "Action impossible."
            messages.error(self.request, message, extra_tags="toast")
            return HttpResponseRedirect(
                reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk})
            )

        # Redirect to first step if form data is not retrieved in session (eg. direct url access)
        if kwargs.get("step") in [
            self.STEP_JOB_SEEKER_ANSWER,
            self.STEP_PRESCRIBER_ANSWER,
        ] and not self.get_cleaned_data_for_step(self.STEP_REASON):
            return HttpResponseRedirect(self.get_step_url(self.STEP_REASON))

    def get(self, *args, **kwargs):
        if check_response := self.check_wizard_state(*args, **kwargs):
            return check_response
        return super().get(*args, **kwargs)

    def post(self, *args, **kwargs):
        if check_response := self.check_wizard_state(*args, **kwargs):
            return check_response
        return super().post(*args, **kwargs)

    def done(self, form_list, *args, **kwargs):
        try:
            # After each successful transition, a save() is performed by django-xworkflows.
            cleaned_data = self.get_all_cleaned_data()
            self.job_application.refusal_reason = cleaned_data["refusal_reason"]
            self.job_application.refusal_reason_shared_with_job_seeker = cleaned_data[
                "refusal_reason_shared_with_job_seeker"
            ]
            self.job_application.answer = cleaned_data["job_seeker_answer"]
            self.job_application.answer_to_prescriber = cleaned_data.get("prescriber_answer", "")
            self.job_application.refuse(user=self.request.user)
            messages.success(
                self.request,
                f"La candidature de {self.job_application.job_seeker.get_full_name()} a bien été déclinée.",
                extra_tags="toast",
            )
        except xwf_models.InvalidTransitionError:
            messages.error(self.request, "Action déjà effectuée.", extra_tags="toast")

        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk})
        return HttpResponseRedirect(next_url)

    def get_prefix(self, request, *args, **kwargs):
        """
        Ensure that each refuse session is bound to a job application.
        Avoid session conflicts when using multiple tabs.
        """
        return f"job_application_{self.job_application.pk}_refuse"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.steps.current != self.STEP_REASON:
            cleaned_data = self.get_cleaned_data_for_step(self.STEP_REASON)
            context["refusal_reason_label"] = job_applications_enums.RefusalReason(
                cleaned_data["refusal_reason"]
            ).label
            context["refusal_reason_shared_with_job_seeker"] = cleaned_data["refusal_reason_shared_with_job_seeker"]
        return context | {
            "job_application": self.job_application,
            "can_view_personal_information": True,  # SIAE members have access to personal info
            "matomo_custom_title": "Candidature refusée",
            "primary_button_label": "Suivant" if context["wizard"]["steps"].next else "Confirmer le refus",
            "secondary_button_label": "Précédent" if context["wizard"]["steps"].prev else "Annuler",
        }

    def get_form_kwargs(self, step=None):
        if step in (self.STEP_REASON, self.STEP_PRESCRIBER_ANSWER):
            return {
                "job_application": self.job_application,
            }
        return {}

    def get_form_initial(self, step):
        initial_data = self.initial_dict.get(step, {})
        if step == self.STEP_JOB_SEEKER_ANSWER:
            refusal_reason = self.get_cleaned_data_for_step(self.STEP_REASON).get("refusal_reason")
            if refusal_reason:
                initial_data["job_seeker_answer"] = loader.render_to_string(
                    f"apply/refusal_messages/{refusal_reason}.txt",
                    context={
                        "job_application": self.job_application,
                    },
                    request=self.request,
                )

        return initial_data

    def get_step_url(self, step):
        return reverse(f"apply:{self.url_name}", kwargs={"job_application_id": self.job_application.pk, "step": step})


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
            messages.success(
                request,
                f"La candidature de {job_application.job_seeker.get_full_name()} a bien été mise en liste d'attente.",
                extra_tags="toast",
            )
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.", extra_tags="toast")

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
    if not job_application.hiring_without_approval and job_application.eligibility_diagnosis_by_siae_required():
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

    def setup(self, request, company_pk=None, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        company = get_object_or_404(Company.objects.member_required(request.user), pk=company_pk)
        self.form_accept = AcceptForm(company=company, data=request.POST or None)

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
            messages.error(request, "Action déjà effectuée.", extra_tags="toast")
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
        job_applications_enums.JobApplicationState.REFUSED,
        job_applications_enums.JobApplicationState.CANCELLED,
        job_applications_enums.JobApplicationState.OBSOLETE,
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
            messages.success(request, success_message, extra_tags="toast")
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.", extra_tags="toast")

    return HttpResponseRedirect(next_url)


@login_required
def transfer(request, job_application_id):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, pk=job_application_id)
    target_company = get_object_or_404(Company.objects, pk=request.POST.get("target_company_id"))
    back_url = get_safe_url(request, "back_url", reverse("apply:list_for_siae"))

    try:
        job_application.transfer(user=request.user, target_company=target_company)
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
            extra_tags="toast",
        )

    return HttpResponseRedirect(back_url)


class JobApplicationExternalTransferStep1View(LoginRequiredMixin, EmployerSearchView):
    job_application = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user)
                .filter(state=job_applications_enums.JobApplicationState.REFUSED)
                .select_related("job_seeker", "to_company"),
                pk=kwargs["job_application_id"],
            )

    def dispatch(self, request, *args, **kwargs):
        if self.job_application and not request.GET:
            return HttpResponseRedirect(f"{request.path}?city={self.job_application.to_company.city_slug}")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "progress": 25,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
        }

    def get_template_names(self):
        return [
            "search/includes/siaes_search_results.html"
            if self.request.htmx
            else "apply/process_external_transfer_siaes_search_results.html"
        ]


class JobApplicationExternalTransferStep1CompanyCardView(LoginRequiredMixin, CompanyCardView):
    def setup(self, request, job_application_id, company_pk, *args, **kwargs):
        super().setup(request, company_pk, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user).not_archived(),
                id=job_application_id,
            )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
        }


class JobApplicationExternalTransferStep1JobDescriptionCardView(LoginRequiredMixin, JobDescriptionCardView):
    def setup(self, request, job_application_id, job_description_id, *args, **kwargs):
        super().setup(request, job_description_id, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user).not_archived(),
                id=job_application_id,
            )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
        }


class ApplicationOverrideMixin:
    additionnal_related_models = []

    def setup(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user).select_related(
                    "job_seeker", "to_company", *self.additionnal_related_models
                ),
                pk=kwargs["job_application_id"],
            )
            kwargs["job_seeker_public_id"] = self.job_application.job_seeker.public_id
        return super().setup(request, *args, **kwargs)


class JobApplicationExternalTransferStep2View(ApplicationOverrideMixin, ApplicationJobsView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and self.company in request.organizations:
            # This is not an external transfer
            url = reverse(
                "apply:job_application_internal_transfer",
                kwargs={"job_application_id": self.job_application.pk, "company_pk": self.company.pk},
            )
            if params := request.GET.urlencode():
                url = f"{url}?{params}"
            return HttpResponseRedirect(url)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        selected_jobs = []
        if job_id := self.request.GET.get("job_description_id"):
            selected_jobs.append(job_id)
        return {"selected_jobs": selected_jobs}

    def get_next_url(self):
        base_url = reverse(
            "apply:job_application_external_transfer_step_3",
            kwargs={
                "job_application_id": self.job_application.pk,
                "company_pk": self.company.pk,
            },
        )
        return f"{base_url}?back_url={quote(self.request.get_full_path())}"

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_app_to_transfer": self.job_application,
            "step": 2,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk}),
            "page_title": "Transférer la candidature",
        }

    def get_back_url(self):
        return get_safe_url(self.request, "back_url")


class JobApplicationExternalTransferStep3View(ApplicationOverrideMixin, ApplicationResumeView):
    additionnal_related_models = ["sender", "sender_company", "sender_prescriber_organization"]
    template_name = "apply/process_external_transfer_resume.html"
    form_class = TransferJobApplicationForm

    def get_initial(self):
        sender_display = self.job_application.sender.get_full_name()
        if self.job_application.sender_company:
            sender_display += f" {self.job_application.sender_company.name}"
        elif self.job_application.sender_prescriber_organization:
            sender_display += f" - {self.job_application.sender_prescriber_organization.name}"
        initial_message = (
            f"Le {self.job_application.created_at.strftime('%d/%m/%Y à %Hh%M')}, {sender_display} a écrit :\n\n"
            + self.job_application.message
        )
        return super().get_initial() | {"message": initial_message}

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"original_job_application": self.job_application}

    def form_valid(self):
        new_job_application = super().form_valid()
        self.job_application.external_transfer(target_company=self.company, user=self.request.user)
        if self.form.cleaned_data.get("keep_original_resume"):
            new_job_application.resume_link = self.job_application.resume_link
            new_job_application.save()
        return new_job_application

    def get_next_url(self, job_application):
        return reverse(
            "apply:job_application_external_transfer_step_end", kwargs={"job_application_id": job_application.pk}
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_app_to_transfer": self.job_application,
            "step": 3,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk}),
            "page_title": "Transférer la candidature",
        }

    def get_back_url(self):
        return get_safe_url(self.request, "back_url")


class JobApplicationExternalTransferStepEndView(ApplicationEndView):
    def setup(self, request, *args, **kwargs):
        job_app_qs = JobApplication.objects.all()
        if request.user.is_authenticated:
            # Only check the user's ownership if he's authenticated
            # because if he's not he will be redirected to login so we don't care
            job_app_qs = JobApplication.objects.prescriptions_of(request.user, request.current_organization)

        job_application = get_object_or_404(job_app_qs, pk=kwargs["job_application_id"])

        return super().setup(
            request,
            *args,
            application_pk=kwargs["job_application_id"],
            company_pk=job_application.to_company_id,
            **kwargs,
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "page_title": "Candidature transférée",
        }


class JobApplicationInternalTranferView(LoginRequiredMixin, TemplateView):
    template_name = "apply/process_internal_transfer.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user).select_related(
                    "job_seeker", "to_company"
                ),
                pk=kwargs["job_application_id"],
            )
            self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=kwargs["company_pk"])

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_app_to_transfer": self.job_application,
            "company": self.company,
            "progress": 75,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk}),
            "back_url": get_safe_url(self.request, "back_url"),
        }


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
                # GEIQ cannot require IAE eligibility diagnosis, but shared templates need this variable.
                "eligibility_diagnosis_by_siae_required": False,
                "geiq_eligibility_diagnosis": (
                    _get_geiq_eligibility_diagnosis(job_application, only_prescriber=False)
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
                # GEIQ cannot require IAE eligibility diagnosis, but shared templates need this variable.
                "eligibility_diagnosis_by_siae_required": False,
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
                geiq_eligibility_diagnosis = _get_geiq_eligibility_diagnosis(job_application, only_prescriber=False)
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
                    # GEIQ cannot require IAE eligibility diagnosis, but shared templates need this variable.
                    "eligibility_diagnosis_by_siae_required": False,
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
