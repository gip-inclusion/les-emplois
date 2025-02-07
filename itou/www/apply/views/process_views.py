import datetime
import logging
from urllib.parse import quote, urljoin

import httpx
import sentry_sdk
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template import loader
from django.urls import reverse, reverse_lazy
from django.utils import formats, timezone
from django.views.decorators.http import require_POST
from django.views.generic.base import TemplateView
from django_xworkflows import models as xwf_models

from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.rdv_insertion.api import get_api_credentials, get_invitation_status
from itou.rdv_insertion.models import Invitation, InvitationRequest, Participation
from itou.users.enums import Title
from itou.utils.auth import check_user
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    AcceptForm,
    AnswerForm,
    PriorActionForm,
    TransferJobApplicationForm,
)
from itou.www.apply.views import common as common_views, constants as apply_view_constants
from itou.www.apply.views.submit_views import ApplicationEndView, ApplicationJobsView, ApplicationResumeView
from itou.www.companies_views.views import CompanyCardView, JobDescriptionCardView
from itou.www.search.views import EmployerSearchView


logger = logging.getLogger(__name__)


JOB_APP_DETAILS_FOR_COMPANY_BACK_URL_KEY = "JOB_APP_DETAILS_FOR_COMPANY-BACK_URL-%d"


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
        # or None if the viewer is a prescriber and the diangosis was made by the company
        # NB. the job application may not have a geiq diagnosis
        if only_prescriber and getattr(job_application.geiq_eligibility_diagnosis, "author_geiq", None):
            return None
        return job_application.geiq_eligibility_diagnosis
    return GEIQEligibilityDiagnosis.objects.diagnoses_for(
        job_application.job_seeker,
        job_application.to_company if not only_prescriber else None,
    ).first()


def job_application_sender_left_org(job_app):
    if org_id := job_app.sender_prescriber_organization_id:
        return not job_app.sender.prescribermembership_set.active().filter(organization_id=org_id).exists()
    if company_id := job_app.sender_company_id:
        return not job_app.sender.companymembership_set.active().filter(company_id=company_id).exists()
    return False


def details_for_jobseeker(request, job_application_id, template_name="apply/process_details.html"):
    """
    Detail of an application for a JOBSEEKER
    """
    job_application = get_object_or_404(
        JobApplication.objects.annotate(
            upcoming_participations_count=Count(
                "job_seeker__rdvi_participations",
                filter=Q(
                    job_seeker__rdvi_participations__appointment__company=F("to_company"),
                    job_seeker__rdvi_participations__status=Participation.Status.UNKNOWN,
                    job_seeker__rdvi_participations__appointment__start_at__gt=timezone.now(),
                ),
            ),
        )
        .select_related(
            "job_seeker__jobseeker_profile",
            "sender",
            "to_company",
            "eligibility_diagnosis__author",
            "eligibility_diagnosis__author_siae",
            "eligibility_diagnosis__author_prescriber_organization",
            "eligibility_diagnosis__job_seeker__jobseeker_profile",
        )
        .prefetch_related(
            "selected_jobs",
            "eligibility_diagnosis__selected_administrative_criteria__administrative_criteria",
            "geiq_eligibility_diagnosis__selected_administrative_criteria__administrative_criteria",
        ),
        id=job_application_id,
        job_seeker=request.user,
    )
    participations = (
        job_application.job_seeker.rdvi_participations.filter(appointment__company=job_application.to_company)
        .select_related("appointment", "appointment__location")
        .order_by("-appointment__start_at")
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
    if geiq_eligibility_diagnosis:
        geiq_eligibility_diagnosis.criteria_display = geiq_eligibility_diagnosis.get_criteria_display_qs(
            hiring_start_at=job_application.hiring_start_at
        )
    eligibility_diagnosis = job_application.get_eligibility_diagnosis()
    if eligibility_diagnosis:
        eligibility_diagnosis.criteria_display = eligibility_diagnosis.get_criteria_display_qs(
            hiring_start_at=job_application.hiring_start_at
        )

    context = {
        "can_view_personal_information": request.user.can_view_personal_information(job_application.job_seeker),
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "display_refusal_info": False,
        "eligibility_diagnosis": eligibility_diagnosis,
        "expired_eligibility_diagnosis": expired_eligibility_diagnosis,
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "job_application": job_application,
        "participations": participations,
        "transition_logs": transition_logs,
        "back_url": back_url,
        "matomo_custom_title": "Candidature",
        "job_application_sender_left_org": job_application_sender_left_org(job_application),
    }

    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def details_for_company(request, job_application_id, template_name="apply/process_details_company.html"):
    """
    Detail of an application for an SIAE with the ability:
    - to update start date of a contract (provided given date is in the future),
    - to give an answer.
    """
    queryset = (
        JobApplication.objects.is_active_company_member(request.user)
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
            "archived_by",
        )
        .prefetch_related(
            "selected_jobs__appellation",
            "eligibility_diagnosis__selected_administrative_criteria__administrative_criteria",
            "geiq_eligibility_diagnosis__selected_administrative_criteria__administrative_criteria",
        )
        .annotate(
            has_pending_rdv_insertion_invitation_request=Exists(
                InvitationRequest.objects.filter(
                    company=OuterRef("to_company"),
                    job_seeker=OuterRef("job_seeker"),
                    created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
                )
            ),
            upcoming_participations_count=Count(
                "job_seeker__rdvi_participations",
                filter=Q(
                    job_seeker__rdvi_participations__appointment__company=request.current_organization,
                    job_seeker__rdvi_participations__status=Participation.Status.UNKNOWN,
                    job_seeker__rdvi_participations__appointment__start_at__gt=timezone.now(),
                ),
            ),
        )
    )
    job_application = get_object_or_404(queryset, id=job_application_id)
    invitation_requests = InvitationRequest.objects.filter(
        company=job_application.to_company,
        job_seeker=job_application.job_seeker,
        created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
    ).prefetch_related("invitations")
    participations = (
        job_application.job_seeker.rdvi_participations.filter(appointment__company=job_application.to_company)
        .select_related("appointment", "appointment__location")
        .order_by("-appointment__start_at")
    )

    transition_logs = job_application.logs.select_related("user").all()

    expired_eligibility_diagnosis = EligibilityDiagnosis.objects.last_expired(
        job_seeker=job_application.job_seeker, for_siae=job_application.to_company
    )

    # get back_url from GET params or session or fallback value
    session_key = JOB_APP_DETAILS_FOR_COMPANY_BACK_URL_KEY % job_application.pk
    fallback_url = request.session.get(session_key, reverse_lazy("apply:list_for_siae"))
    back_url = get_safe_url(request, "back_url", fallback_url=fallback_url)
    request.session[session_key] = back_url

    geiq_eligibility_diagnosis = (
        job_application.to_company.kind == CompanyKind.GEIQ
        and _get_geiq_eligibility_diagnosis(job_application, only_prescriber=False)
    )
    if geiq_eligibility_diagnosis:
        geiq_eligibility_diagnosis.criteria_display = geiq_eligibility_diagnosis.get_criteria_display_qs(
            hiring_start_at=job_application.hiring_start_at
        )

    eligibility_diagnosis = job_application.get_eligibility_diagnosis()
    if eligibility_diagnosis:
        eligibility_diagnosis.criteria_display = eligibility_diagnosis.get_criteria_display_qs(
            hiring_start_at=job_application.hiring_start_at
        )

    can_be_cancelled = job_application.state.is_accepted and job_application.can_be_cancelled

    context = {
        "can_be_cancelled": can_be_cancelled,
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "can_edit_personal_information": request.user.can_edit_personal_information(job_application.job_seeker),
        "display_refusal_info": False,
        "eligibility_diagnosis": eligibility_diagnosis,
        "eligibility_diagnosis_by_siae_required": job_application.eligibility_diagnosis_by_siae_required(),
        "expired_eligibility_diagnosis": expired_eligibility_diagnosis,
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "job_application": job_application,
        "invitation_requests": invitation_requests,
        "participations": participations,
        "transition_logs": transition_logs,
        "back_url": back_url,
        "add_prior_action_form": (
            PriorActionForm(action_only=True) if job_application.can_change_prior_actions else None
        ),
        "matomo_custom_title": "Candidature",
        "job_application_sender_left_org": job_application_sender_left_org(job_application),
    }

    return render(request, template_name, context)


@check_user(lambda u: u.is_prescriber or u.is_employer)
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
        "archived_by",
    ).prefetch_related(
        "selected_jobs__appellation",
        "eligibility_diagnosis__selected_administrative_criteria__administrative_criteria",
        "geiq_eligibility_diagnosis__selected_administrative_criteria__administrative_criteria",
    )
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
    if geiq_eligibility_diagnosis:
        geiq_eligibility_diagnosis.criteria_display = geiq_eligibility_diagnosis.get_criteria_display_qs(
            hiring_start_at=job_application.hiring_start_at
        )

    eligibility_diagnosis = job_application.get_eligibility_diagnosis()
    if eligibility_diagnosis:
        eligibility_diagnosis.criteria_display = eligibility_diagnosis.get_criteria_display_qs(
            hiring_start_at=job_application.hiring_start_at
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
        "eligibility_diagnosis": eligibility_diagnosis,
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "expired_eligibility_diagnosis": None,  # XXX: should we search for an expired diagnosis here ?
        "job_application": job_application,
        "participations": [],
        "transition_logs": transition_logs,
        "back_url": back_url,
        "matomo_custom_title": "Candidature",
        "display_refusal_info": display_refusal_info,
        "refused_by": refused_by,
        "refusal_contact_email": refusal_contact_email,
        "with_job_seeker_detail_url": True,
        "job_application_sender_left_org": job_application_sender_left_org(job_application),
    }

    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer)
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


@check_user(lambda user: user.is_employer)
def start_refuse_wizard(request, job_application_id):
    from itou.www.apply.views.batch_views import _start_refuse_wizard

    return _start_refuse_wizard(
        request,
        application_ids=[job_application_id],
        next_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application_id}),
        from_detail_view=True,
    )


@check_user(lambda user: user.is_employer)
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


@check_user(lambda user: user.is_employer)
def accept(request, job_application_id, template_name="apply/process_accept.html"):
    """
    Trigger the `accept` transition.
    """
    queryset = JobApplication.objects.is_active_company_member(request.user).select_related(
        "job_seeker", "job_seeker__jobseeker_profile"
    )
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


class AcceptHTMXFragmentView(UserPassesTestMixin, TemplateView):
    NO_ERROR_FIELDS = []

    def test_func(self):
        return self.request.user.is_employer

    def setup(self, request, company_pk=None, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        company = get_object_or_404(
            Company.objects.filter(pk__in={org.pk for org in request.organizations}), pk=company_pk
        )
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


@require_POST
@check_user(lambda user: user.is_employer)
def cancel(request, job_application_id):
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

    try:
        # After each successful transition, a save() is performed by django-xworkflows.
        job_application.cancel(user=request.user)
        messages.success(request, "L'embauche a bien été annulée.", extra_tags="toast")
    except xwf_models.InvalidTransitionError:
        messages.error(request, "Action déjà effectuée.", extra_tags="toast")
    return HttpResponseRedirect(next_url)


@check_user(lambda user: user.is_employer)
def transfer(request, job_application_id):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, pk=job_application_id)
    target_company = get_object_or_404(Company.objects, pk=request.POST.get("target_company_id"))

    session_key = JOB_APP_DETAILS_FOR_COMPANY_BACK_URL_KEY % job_application.pk
    fallback_url = request.session.get(session_key, reverse_lazy("apply:list_for_siae"))
    back_url = get_safe_url(request, "back_url", fallback_url=fallback_url)

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
                JobApplication.objects.is_active_company_member(request.user),
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
                JobApplication.objects.is_active_company_member(request.user),
                id=job_application_id,
            )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
            "can_update_job_description": False,
        }


class ApplicationOverrideMixin:
    additionnal_related_models = []

    def setup(self, request, *args, **kwargs):
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
        if self.company in request.organizations:
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

    def dispatch(self, request, *args, **kwargs):
        if not self.apply_session.exists():
            return HttpResponseRedirect(
                reverse(
                    "apply:job_application_external_transfer_step_2",
                    kwargs={"job_application_id": self.job_application.pk, "company_pk": self.company.pk},
                )
            )
        return super().dispatch(request, *args, **kwargs)

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
        return {"message": initial_message}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial = kwargs.get("initial", {})
        initial.update(self.get_initial())
        kwargs["initial"] = initial
        kwargs["original_job_application"] = self.job_application
        return kwargs

    def form_valid(self):
        new_job_application = super().form_valid()
        self.job_application.external_transfer(target_company=self.company, user=self.request.user)
        if self.form.cleaned_data.get("keep_original_resume"):
            new_job_application.resume_link = self.job_application.resume_link
            new_job_application.save(update_fields={"resume_link"})
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


class JobApplicationInternalTranferView(TemplateView):
    template_name = "apply/process_internal_transfer.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_application = get_object_or_404(
            JobApplication.objects.is_active_company_member(request.user).select_related("job_seeker", "to_company"),
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


@require_POST
@check_user(lambda user: user.is_employer)
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


@check_user(lambda user: user.is_employer)
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


@check_user(lambda user: user.is_employer)
def geiq_eligibility(request, job_application_id, template_name="apply/process_geiq_eligibility.html"):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    # Check GEIQ eligibility during job application process
    job_application = get_object_or_404(queryset, pk=job_application_id)
    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
    )
    next_url = get_safe_url(request, "next_url")
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


@check_user(lambda user: user.is_employer)
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
@check_user(lambda user: user.is_employer)
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


@check_user(lambda user: user.is_employer)
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
                "add_prior_action_form": None,
                "with_oob_state_update": False,
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
        "main_div_id": f"prior-action-{prior_action.pk}" if prior_action else "add_prior_action",
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


@require_POST
@check_user(lambda user: user.is_employer)
def rdv_insertion_invite(request, job_application_id, for_detail=False):
    if for_detail:
        template_name = "apply/includes/invitation_requests.html"
    else:
        template_name = "apply/includes/buttons/rdv_insertion_invite.html"

    try:
        job_application = (
            JobApplication.objects.is_active_company_member(request.user)
            .select_related("job_seeker__jobseeker_profile", "to_company")
            .annotate(
                has_pending_rdv_insertion_invitation_request=Exists(
                    InvitationRequest.objects.filter(
                        company=OuterRef("to_company"),
                        job_seeker=OuterRef("job_seeker"),
                        created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
                    )
                )
            )
            .get(id=job_application_id)
        )
    except JobApplication.DoesNotExist:
        return render(
            request,
            template_name,
            {"job_application": None, "invitation_requests": None, "state": "error"},
        )

    # Ensure company has RDV-I configured
    if not job_application.to_company.rdv_solidarites_id:
        return render(
            request,
            template_name,
            {"job_application": None, "invitation_requests": None, "state": "error"},
        )

    if for_detail:
        invitation_requests = InvitationRequest.objects.filter(
            job_seeker=job_application.job_seeker,
            company=job_application.to_company,
            created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
        )
    else:
        invitation_requests = None

    if not job_application.has_pending_rdv_insertion_invitation_request:
        try:
            with transaction.atomic():
                url = urljoin(
                    settings.RDV_INSERTION_API_BASE_URL,
                    f"organisations/{job_application.to_company.rdv_solidarites_id}/users/create_and_invite",
                )
                headers = {"Content-Type": "application/json; charset=utf-8", **get_api_credentials()}

                data = {
                    "user": {
                        "first_name": job_application.job_seeker.first_name,  # Required
                        "last_name": job_application.job_seeker.last_name,  # Required
                        "title": (
                            "madame" if job_application.job_seeker.title == Title.MME else "monsieur"
                        ),  # Required!
                        "role": "demandeur",  # Required
                        "email": job_application.job_seeker.email,
                        "phone_number": job_application.job_seeker.phone,
                        "birth_date": (
                            formats.date_format(job_application.job_seeker.jobseeker_profile.birthdate, "d/m/Y")
                            if job_application.job_seeker.jobseeker_profile.birthdate
                            else None
                        ),
                        "address": job_application.job_seeker.address_on_one_line,
                        "invitation": {
                            "motif_category": {
                                "short_name": "siae_interview",
                            },
                        },
                    },
                }

                response = httpx.post(url=url, headers=headers, json=data, timeout=10)
                if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                    headers = get_api_credentials(refresh=True)
                    response = httpx.post(url=url, headers=headers, json=data, timeout=10)
                response_data = response.raise_for_status().json()

                invitation_request = InvitationRequest.objects.create(
                    job_seeker=job_application.job_seeker,
                    company=job_application.to_company,
                    api_response=response_data,
                    reason_category=InvitationRequest.ReasonCategory.SIAE_INTERVIEW,
                    rdv_insertion_user_id=response_data["user"]["id"],
                )
                invitations = []
                for invitation in response_data["invitations"]:
                    extra_kwargs = {}
                    if invitation_status := get_invitation_status(invitation):
                        extra_kwargs["status"] = invitation_status
                    if delivered_at_str := invitation.get("delivered_at"):
                        try:
                            extra_kwargs["delivered_at"] = datetime.datetime.fromisoformat(delivered_at_str)
                        except Exception as e:
                            # RDV-I API date formats are not consistent:
                            # Let us know if anything has changed without causing failure
                            logger.exception(e)
                    invitations.append(
                        Invitation(
                            type=Invitation.Type(invitation["format"]),
                            invitation_request=invitation_request,
                            rdv_insertion_id=invitation["id"],
                            **extra_kwargs,
                        )
                    )
                Invitation.objects.bulk_create(invitations)

                if for_detail:
                    # Refresh invitation requests
                    invitation_requests = InvitationRequest.objects.filter(
                        job_seeker=job_application.job_seeker,
                        company=job_application.to_company,
                        created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
                    )
        except Exception as e:
            sentry_sdk.capture_exception(e)
            return render(
                request,
                template_name,
                {"job_application": job_application, "invitation_requests": invitation_requests, "state": "error"},
            )

    job_application.has_pending_rdv_insertion_invitation_request = True

    return render(
        request,
        template_name,
        {"job_application": job_application, "invitation_requests": invitation_requests, "state": "ok"},
    )
