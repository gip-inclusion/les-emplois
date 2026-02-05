import logging

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import Http404, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_safe
from django.views.generic.base import TemplateView

from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.job_applications.models import (
    JobApplication,
)
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.session import SessionNamespace, SessionNamespaceException
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    AcceptForm,
)
from itou.www.apply.views import common as common_views, constants as apply_view_constants


logger = logging.getLogger(__name__)

ACCEPT_SESSION_KIND = "accept_session"


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


def initialize_accept_session(request, data):
    return SessionNamespace.create(request.session, ACCEPT_SESSION_KIND, data)


@require_safe
@check_user(lambda user: user.is_employer)
def start_accept_wizard(request, job_application_id):
    queryset = JobApplication.objects.is_active_company_member(request.user).select_related(
        "job_seeker", "job_seeker__jobseeker_profile", "to_company"
    )
    job_application = get_object_or_404(queryset, id=job_application_id)
    check_waiting_period(job_application)

    next_url = get_safe_url(
        request,
        "next_url",
        reverse("apply:details_for_company", kwargs={"job_application_id": job_application_id}),
    )

    data = {
        "reset_url": next_url,
        "job_application_id": job_application_id,
    }
    session = initialize_accept_session(request, data)
    return HttpResponseRedirect(reverse("apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session.name}))


class AcceptWizardMixin:
    def __init__(self):
        self.accept_session = None
        self.job_seeker = None
        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None

    def setup(self, request, *args, session_uuid, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.accept_session = SessionNamespace(request.session, ACCEPT_SESSION_KIND, session_uuid)
        except SessionNamespaceException:
            raise Http404
        job_application_id = self.accept_session.get("job_application_id")
        self.reset_url = self.accept_session.get("reset_url")  # store it before possible session deletion
        queryset = JobApplication.objects.is_active_company_member(request.user).select_related(
            "job_seeker", "job_seeker__jobseeker_profile", "to_company"
        )
        self.job_application = get_object_or_404(queryset, id=job_application_id)
        self.company = self.job_application.to_company
        self.job_seeker = self.job_application.job_seeker
        check_waiting_period(self.job_application)
        if self.company.kind == CompanyKind.GEIQ:
            self.geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.job_seeker, self.company
            ).first()
        elif self.company.is_subject_to_iae_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, self.company
            )

    def get_reset_url(self):
        return self.reset_url

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "reset_url": self.get_reset_url(),
        }

    def get_eligibility_view_name(self):
        if self.job_application.eligibility_diagnosis_by_siae_required():
            return "apply:eligibility"
        elif self.company.kind == CompanyKind.GEIQ and self.geiq_eligibility_diagnosis is None:
            return "apply:geiq_eligibility"
        return None


class FillJobSeekerInfosForAcceptView(AcceptWizardMixin, common_views.BaseFillJobSeekerInfosView):
    template_name = "apply/process_accept_fill_job_seeker_infos_step.html"

    def get_session(self):
        return self.accept_session

    def get_back_url(self):
        return None  # First step of the wizard: no back url

    def get_success_url(self):
        return reverse("apply:accept_contract_infos", kwargs={"session_uuid": self.accept_session.name})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.eligibility_diagnosis:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            self.eligibility_diagnosis.job_seeker = self.job_seeker

        context["expired_eligibility_diagnosis"] = None
        return context


class ContractInfosForAcceptView(AcceptWizardMixin, common_views.BaseContractInfosView):
    template_name = "apply/process_accept_contract_infos_step.html"

    def setup(self, request, *args, **kwargs):
        self.job_application = None
        return super().setup(request, *args, **kwargs)

    def get_session(self):
        return self.accept_session

    def get_back_url(self):
        other_forms = {k: v for k, v in self.forms.items() if k != "accept"}
        if other_forms:
            return reverse("apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": self.accept_session.name})
        return None

    def get_success_url(self):
        next_url = reverse("apply:accept_confirmation", kwargs={"session_uuid": self.accept_session.name})
        if eligibility_view_name := self.get_eligibility_view_name():
            return reverse(
                eligibility_view_name,
                kwargs={"job_application_id": self.job_application.pk},
                query={"next_url": next_url, "back_url": self.request.get_full_path()},
            )
        return next_url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.eligibility_diagnosis:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            self.eligibility_diagnosis.job_seeker = self.job_seeker

        context["expired_eligibility_diagnosis"] = None
        return context


class AcceptHTMXFragmentView(UserPassesTestMixin, TemplateView):
    NO_ERROR_FIELDS = []

    def test_func(self):
        return self.request.user.is_employer

    def setup(self, request, company_pk=None, job_seeker_public_id=None, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        company = get_object_or_404(
            Company.objects.filter(pk__in={org.pk for org in request.organizations}), pk=company_pk
        )
        job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id)
        self.form_accept = AcceptForm(company=company, job_seeker=job_seeker, data=request.POST or None)

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


class ConfirmationForAcceptView(AcceptWizardMixin, common_views.BaseConfirmationView):
    template_name = "apply/process_accept_confirmation_step.html"

    def get_session(self):
        return self.accept_session

    def clean_session(self):
        self.accept_session.delete()

    def get_error_url(self):
        return self.request.get_full_path()

    def get_back_url(self):
        back_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": self.accept_session.name})
        if eligibility_view_name := self.get_eligibility_view_name():
            # Typically if GEIQ diagnosis wasn't created
            return reverse(
                eligibility_view_name,
                kwargs={"job_application_id": self.job_application.pk},
                query={"back_url": back_url, "next_url": self.request.get_full_path()},
            )
        return back_url

    def get_success_url(self):
        return self.reset_url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["job_application"] = self.job_application
        context["job_seeker"] = self.job_seeker
        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["matomo_custom_title"] = "Confirmation d'acceptation de candidature"
        return context

    def missing_steps_redirect(self):
        redirect = super().missing_steps_redirect()
        if redirect is None and self.job_application.eligibility_diagnosis_by_siae_required():
            # This should not happen
            messages.error(
                self.request,
                "Cette candidature requiert un diagnostic d'éligibilité pour être acceptée.",
                extra_tags="toast",
            )
            redirect = HttpResponseRedirect(
                reverse(
                    self.get_eligibility_view_name(),
                    kwargs={"job_application_id": self.job_application.pk},
                    query={"next_url": self.request.get_full_path()},
                )
            )
        return redirect
