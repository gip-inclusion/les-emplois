import logging

from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import View

from itou.companies.models import Company
from itou.utils.urls import get_safe_url
from itou.www.apply.views import common as common_views
from itou.www.apply.views.submit_views import (
    ApplicationBaseView,
    ApplicationPermissionMixin,
    ApplyTunnel,
    CheckPreviousApplicationsBaseView,
    initialize_apply_session,
)
from itou.www.eligibility_views.views import BaseIAEEligibilityViewForEmployer


logger = logging.getLogger(__name__)


class StartViewForHire(ApplicationPermissionMixin, View):
    def setup(self, request, company_pk, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=company_pk)
        self.tunnel = ApplyTunnel.HIRE
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


class CheckPreviousApplicationsForHireView(CheckPreviousApplicationsBaseView):
    def get_next_url(self):
        return reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": self.apply_session.name})


class IAEEligibilityForHireView(ApplicationBaseView, BaseIAEEligibilityViewForEmployer):
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


class GEIQEligibilityForHireView(ApplicationBaseView, common_views.BaseGEIQEligibilityView):
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


class GEIQEligiblityCriteriaForHireView(ApplicationBaseView, common_views.BaseGEIQEligibilityCriteriaHtmxView):
    pass


class FillJobSeekerInfosForHireView(ApplicationBaseView, common_views.BaseFillJobSeekerInfosView):
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


class ContractInfosForHireView(ApplicationBaseView, common_views.BaseContractInfosView):
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


class ConfirmationForHireView(ApplicationBaseView, common_views.BaseConfirmationView):
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
