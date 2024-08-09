from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import DetailView

from itou.companies.enums import CompanyKind
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.users.models import User


class JobSeekerDatilsViews(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = User
    queryset = User.objects.select_related("jobseeker_profile").prefetch_related()
    template_name = "job_seekers_views/details.html"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"
    context_object_name = "job_seeker"

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.can_view_personal_information(
            self.get_object()
        )

    def get_context_data(self, **kwargs):
        geiq_eligibility_diagnosis = None
        if self.request.user.is_prescriber or self.request.current_organization.kind == CompanyKind.GEIQ:
            geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.object,
                for_geiq=self.request.current_organization if self.request.user.is_employer else None,
            ).first()

        approval = None
        iae_eligibility_diagnosis = None
        if self.request.user.is_prescriber or self.request.current_organization.is_subject_to_eligibility_rules:
            approval = self.object.approvals.valid().first()
            iae_eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.object,
                for_siae=self.request.current_organization if self.request.user.is_employer else None,
            )

        return super().get_context_data(**kwargs) | {
            "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
            "iae_eligibility_diagnosis": iae_eligibility_diagnosis,
            "matomo_custom_title": "Détail candidat",
            "approval": approval,
            # already checked in test_func because the user name is displayed in the title
            "can_view_personal_information": True,
            "can_edit_personal_information": self.request.user.can_edit_personal_information(self.object),
        }
