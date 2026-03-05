import logging

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
from itou.www.apply.views.submit_views import (
    APPLY_SESSION_KIND,
    JOB_SEEKER_INFOS_CHECK_PERIOD,
    CheckPreviousApplicationsBaseMixin,
    _check_job_seeker_approval,
    initialize_apply_session,
)
from itou.www.eligibility_views.views import BaseIAEEligibilityViewForEmployer


logger = logging.getLogger(__name__)


class HirePermissionMixin:
    """
    This mixin requires the following argument that must be setup by the child view

    company: Company
    """

    def get_reset_url(self):
        raise NotImplementedError

    def dispatch(self, request, *args, **kwargs):
        if request.user.kind != UserKind.EMPLOYER:
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
        self.apply_session = initialize_apply_session(
            request, {"reset_url": self.reset_url, "company_pk": self.company.pk}
        )

        params = {
            "tunnel": "hire",
            "apply_session_uuid": self.apply_session.name,
            "company": self.company.pk,
            "from_url": self.get_reset_url(),
        }

        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        return HttpResponseRedirect(next_url)


class HireBaseView(HirePermissionMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.apply_session = None
        self.company = None
        self.job_seeker = None
        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None

    def setup(self, request, *args, session_uuid, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.apply_session = SessionNamespace(request.session, APPLY_SESSION_KIND, session_uuid)
        except SessionNamespaceException:
            raise Http404
        self.company = get_object_or_404(
            Company.objects.with_has_active_members(), pk=self.apply_session.get("company_pk")
        )

        job_seeker_public_id = self.apply_session.get("job_seeker_public_id") or request.GET.get(
            "job_seeker_public_id"
        )
        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id
        )
        if "job_seeker_public_id" not in self.apply_session:
            self.apply_session.set("job_seeker_public_id", job_seeker_public_id)
        _check_job_seeker_approval(request, self.job_seeker, self.company)
        if self.company.kind == CompanyKind.GEIQ:
            self.geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.job_seeker, self.company
            ).first()
        elif self.company.is_subject_to_iae_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, self.company
            )

    def get_back_url(self):
        return None

    def get_reset_url(self):
        return self.apply_session.get("reset_url")

    def get_eligibility_for_hire_step_url(self):
        if self.company.kind == CompanyKind.GEIQ and not self.geiq_eligibility_diagnosis:
            return reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": self.apply_session.name})

        bypass_eligibility_conditions = [
            # Don't perform an eligibility diagnosis if the SIAE doesn't need it,
            not self.company.is_subject_to_iae_rules,
            # No need for eligibility diagnosis if the job seeker already has a PASS IAE
            self.job_seeker.has_valid_approval,
            # Job seeker must not have a diagnosis
            self.eligibility_diagnosis,
        ]
        if not any(bypass_eligibility_conditions):
            return reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": self.apply_session.name})

        return None

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "company": self.company,
            "back_url": self.get_back_url(),
            "reset_url": self.get_reset_url(),
            "hire_process": True,
            "prescription_process": False,
            "auto_prescription_process": False,
            "page_title": "Postuler",
            "job_seeker": self.job_seeker,
            "eligibility_diagnosis": self.eligibility_diagnosis,
            "is_subject_to_iae_rules": self.company.is_subject_to_iae_rules,
            "geiq_eligibility_diagnosis": self.geiq_eligibility_diagnosis,
            "is_subject_to_geiq_rules": self.company.kind == CompanyKind.GEIQ,
            "can_edit_personal_information": can_edit_personal_information(self.request, self.job_seeker),
            "can_view_personal_information": can_view_personal_information(self.request, self.job_seeker),
            "new_check_needed": self.job_seeker.last_checked_at < timezone.now() - JOB_SEEKER_INFOS_CHECK_PERIOD,
        }


class CheckPreviousApplicationsForHireView(CheckPreviousApplicationsBaseMixin, HireBaseView):
    def get_next_url(self):
        return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.apply_session.name})


class IAEEligibilityForHireView(HireBaseView, BaseIAEEligibilityViewForEmployer):
    template_name = "apply/submit/eligibility_for_hire.html"

    def dispatch(self, request, *args, **kwargs):
        if self.get_eligibility_for_hire_step_url() is None:
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        # Check if contract step is already filled
        if not self.apply_session.get("contract_form_data"):
            # TODO: remove this case in a week
            return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.apply_session.name})
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.apply_session.name})

    def get_cancel_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hire_process"] = True
        return context


class GEIQEligibilityForHireView(HireBaseView, common_views.BaseGEIQEligibilityView):
    template_name = "apply/submit/geiq_eligibility_for_hire.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.geiq_eligibility_criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def dispatch(self, request, *args, **kwargs):
        if self.get_eligibility_for_hire_step_url() is None:
            return HttpResponseRedirect(self.get_next_url())
        return super().dispatch(request, *args, **kwargs)

    def get_next_url(self):
        # Check if contract step is already filled
        if not self.apply_session.get("contract_form_data"):
            # TODO: remove this case in a week
            return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.apply_session.name})
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.apply_session.name})

    def get_back_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
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

    def get_session(self):
        return self.apply_session

    def get_back_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def get_success_url(self):
        return reverse("apply:hire_contract_infos", kwargs={"session_uuid": self.apply_session.name})

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
        return self.apply_session

    def clean_session(self):
        self.apply_session.delete()

    def get_back_url(self):
        other_forms = {k: v for k, v in self.forms.items() if k != "accept"}
        if other_forms:
            return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.apply_session.name})
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def get_success_url(self):
        return self.get_eligibility_for_hire_step_url() or reverse(
            "apply:hire_confirmation", kwargs={"session_uuid": self.apply_session.name}
        )

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
        return self.apply_session

    def clean_session(self):
        self.apply_session.delete()

    def get_back_url(self):
        return reverse("apply:hire_contract_infos", kwargs={"session_uuid": self.apply_session.name})

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
