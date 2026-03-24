import logging

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.utils import can_edit_personal_information, can_view_personal_information
from itou.utils.session import SessionNamespace, SessionNamespaceException
from itou.utils.urls import get_safe_url
from itou.www.apply.views import common as common_views
from itou.www.apply.views.submit_views import _check_job_seeker_approval
from itou.www.eligibility_views.views import BaseIAEEligibilityViewForEmployer


logger = logging.getLogger(__name__)

HIRE_SESSION_KIND = "hire_session"


def initialize_hire_session(request, data):
    return SessionNamespace.create(request.session, HIRE_SESSION_KIND, data)


class HirePermissionMixin:
    """
    This mixin requires the following argument that must be setup by the child view

    company: Company
    """

    def get_reset_url(self):
        raise NotImplementedError

    def dispatch(self, request, *args, **kwargs):
        if not request.from_employer:
            raise PermissionDenied("Seuls les employeurs sont autorisés à déclarer des embauches.")
        if not self.company.has_member(request.user):
            raise PermissionDenied("Vous ne pouvez déclarer une embauche que dans votre structure.")
        if suspension_explanation := self.company.get_active_suspension_text_with_dates():
            raise PermissionDenied(
                "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle "
                "a posteriori. " + suspension_explanation
            )
        return super().dispatch(request, *args, **kwargs)


class StartViewForHire(HirePermissionMixin, View):
    def setup(self, request, company_pk, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=company_pk)
        self.reset_url = get_safe_url(request, "back_url", reverse("dashboard:index"))

    def get_reset_url(self):
        return self.reset_url

    def get(self, request, *args, **kwargs):
        self.hire_session = initialize_hire_session(
            request, {"reset_url": self.reset_url, "company_pk": self.company.pk}
        )

        params = {
            "tunnel": "hire",
            "hire_session_uuid": self.hire_session.name,
            "company": self.company.pk,
            "from_url": self.get_reset_url(),
        }

        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        return HttpResponseRedirect(next_url)


class HireBaseView(HirePermissionMixin, common_views.IsIAEEligibilityDiagnosisNeededMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.hire_session = None
        self.company = None
        self.job_seeker = None
        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None
        self.geiq_eligibility_missing = False

    def setup(self, request, *args, session_uuid, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.hire_session = SessionNamespace(request.session, HIRE_SESSION_KIND, session_uuid)
        except SessionNamespaceException:
            raise Http404
        self.company = get_object_or_404(
            Company.objects.with_has_active_members(), pk=self.hire_session.get("company_pk")
        )

        job_seeker_public_id = self.hire_session.get("job_seeker_public_id") or request.GET.get("job_seeker_public_id")
        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id
        )
        if "job_seeker_public_id" not in self.hire_session:
            self.hire_session.set("job_seeker_public_id", job_seeker_public_id)
        _check_job_seeker_approval(request, self.job_seeker, self.company)
        if self.company.kind == CompanyKind.GEIQ:
            self.geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.job_seeker, self.company
            ).first()
            self.geiq_eligibility_missing = self.geiq_eligibility_diagnosis is None
        elif self.company.is_subject_to_iae_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, self.company
            )

    def get_session(self):
        # Used by BaseFillJobSeekerInfosView, BaseContractInfosView & BaseConfirmationView
        return self.hire_session

    def get_back_url(self):
        return None

    def get_reset_url(self):
        return self.hire_session.get("reset_url")

    def get_contract_infos_url(self):
        return reverse("apply:hire_contract_infos", kwargs={"session_uuid": self.hire_session.name})

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "company": self.company,
            "back_url": self.get_back_url(),
            "reset_url": self.get_reset_url(),
            "hire_process": True,
            "prescription_process": False,
            "auto_prescription_process": False,
            "job_seeker": self.job_seeker,
            "eligibility_diagnosis": self.eligibility_diagnosis,
            "is_subject_to_iae_rules": self.company.is_subject_to_iae_rules,
            "geiq_eligibility_diagnosis": self.geiq_eligibility_diagnosis,
            "is_subject_to_geiq_rules": self.company.kind == CompanyKind.GEIQ,
            "can_edit_personal_information": can_edit_personal_information(self.request, self.job_seeker),
            "can_view_personal_information": can_view_personal_information(self.request, self.job_seeker),
        }


class CheckPreviousApplicationsForHireView(common_views.CheckPreviousApplicationsBaseMixin, HireBaseView):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.prev_applications = (
            common_views.previous_applications_queryset(self.job_seeker, self.company)
            .filter(created_at__gte=timezone.now() - relativedelta(months=12))
            .select_related("sender", "sender_prescriber_organization")
            .exclude(state="accepted")
            .order_by("created_at")
        )
        self.prev_application = self.prev_applications.first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prev_applications"] = self.prev_applications
        return context

    def get_next_url(self):
        return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.hire_session.name})


class IAEEligibilityForHireView(
    common_views.ContractInfosNeededMixin, HireBaseView, BaseIAEEligibilityViewForEmployer
):
    template_name = "apply/submit/eligibility_for_hire.html"

    def dispatch(self, request, *args, **kwargs):
        # If someone tries to access this page for a non-IAE company, let the base class serve a 404
        if self.company.is_subject_to_iae_rules and not self.is_iae_eligibility_diagnosis_needed():
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.hire_session.name})

    def get_cancel_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.hire_session.name}
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hire_process"] = True
        return context


class GEIQEligibilityForHireView(
    common_views.ContractInfosNeededMixin, HireBaseView, common_views.BaseGEIQEligibilityView
):
    template_name = "apply/submit/geiq_eligibility_for_hire.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.geiq_eligibility_criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire", kwargs={"session_uuid": self.hire_session.name}
        )

    def dispatch(self, request, *args, **kwargs):
        # If someone tries to access this page for a non-GEIQ company, let the base class serve a 404
        if self.company.kind == CompanyKind.GEIQ and not self.geiq_eligibility_missing:
            return HttpResponseRedirect(self.get_next_url())
        return super().dispatch(request, *args, **kwargs)

    def get_next_url(self):
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.hire_session.name})

    def get_back_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.hire_session.name}
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hire_process"] = True
        context["is_subject_to_iae_rules"] = False
        return context


class GEIQEligiblityCriteriaForHireView(HireBaseView, common_views.BaseGEIQEligibilityCriteriaHtmxView):
    pass


class FillJobSeekerInfosForHireView(HireBaseView, common_views.BaseFillJobSeekerInfosView):
    template_name = "apply/submit/hire_fill_job_seeker_infos_step.html"

    def setup(self, request, *args, **kwargs):
        self.job_application = None
        return super().setup(request, *args, **kwargs)

    def get_back_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.hire_session.name}
        )

    def get_success_url(self):
        return self.get_contract_infos_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.eligibility_diagnosis:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            self.eligibility_diagnosis.job_seeker = self.job_seeker

        context["expired_eligibility_diagnosis"] = None
        return context


class ContractInfosForHireView(HireBaseView, common_views.BaseContractInfosView):
    template_name = "apply/submit/hire_contract_infos_step.html"

    def setup(self, request, *args, **kwargs):
        self.job_application = None
        return super().setup(request, *args, **kwargs)

    def get_session(self):
        return self.hire_session

    def clean_session(self):
        self.hire_session.delete()

    def get_back_url(self):
        other_forms = {k: v for k, v in self.forms.items() if k != "accept"}
        if other_forms:
            return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.hire_session.name})
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.hire_session.name}
        )

    def get_success_url(self):
        if self.is_iae_eligibility_diagnosis_needed():
            return reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": self.hire_session.name})
        if self.geiq_eligibility_missing:
            return reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": self.hire_session.name})
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.hire_session.name})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.eligibility_diagnosis:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            self.eligibility_diagnosis.job_seeker = self.job_seeker

        context["expired_eligibility_diagnosis"] = None
        return context


class ConfirmationForHireView(HireBaseView, common_views.BaseConfirmationView):
    template_name = "apply/submit/hire_confirmation_step.html"

    def setup(self, request, *args, **kwargs):
        self.job_application = None
        return super().setup(request, *args, **kwargs)

    def get_session(self):
        return self.hire_session

    def clean_session(self):
        self.hire_session.delete()

    def get_back_url(self):
        return self.get_contract_infos_url()

    def get_error_url(self):
        return self.request.get_full_path()

    def get_success_url(self):
        if self.company.is_subject_to_iae_rules and self.job_application.approval:
            return reverse("employees:detail", kwargs={"public_id": self.job_seeker.public_id})
        return reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.eligibility_diagnosis:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            self.eligibility_diagnosis.job_seeker = self.job_seeker

        context["expired_eligibility_diagnosis"] = None
        context["matomo_custom_title"] = "Confirmation d'embauche"
        return context

    def missing_steps_redirect(self):
        redirect = super().missing_steps_redirect()
        if redirect is None and self.is_iae_eligibility_diagnosis_needed():  # GEIQ eligibility might be skipped
            # This should not happen
            messages.error(
                self.request,
                "Un diagnostic d'éligibilité est nécessaire pour déclarer cette embauche.",
                extra_tags="toast",
            )
            redirect = HttpResponseRedirect(
                reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": self.hire_session.name})
            )
        return redirect
