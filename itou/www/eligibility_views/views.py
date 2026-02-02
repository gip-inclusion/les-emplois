from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import FormView

from itou.eligibility.models.iae import EligibilityDiagnosis, get_criteria_from_job_seeker
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.urls import get_safe_url
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


class BaseIAEEligibilityViewForPrescriber(UserPassesTestMixin, FormView):
    template_name = None
    # Any child class should include the following templates :
    # "eligibility/includes/iae_help_for_prescriber.html"
    # "eligibility/includes/iae_form_content_for_prescriber.html"
    form_class = AdministrativeCriteriaForm
    display_success_messages = False

    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        self.criteria_filled_from_job_seeker = None

    def test_func(self):
        return self.request.from_authorized_prescriber

    def dispatch(self, request, *args, **kwargs):
        # No need for eligibility diagnosis if the job seeker already has a PASS IAE
        if self.job_seeker.approvals.valid().exists():
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_authorized_prescriber"] = self.request.from_authorized_prescriber
        kwargs["siae"] = self.company
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.eligibility_diagnosis:
            initial["administrative_criteria"] = self.eligibility_diagnosis.administrative_criteria.all()
        elif self.job_seeker.last_checked_at > timezone.now() - timezone.timedelta(hours=24):
            self.criteria_filled_from_job_seeker = get_criteria_from_job_seeker(self.job_seeker)
            initial["administrative_criteria"] = self.criteria_filled_from_job_seeker
        return initial

    def form_valid(self, form):
        message = None
        if not self.eligibility_diagnosis:
            EligibilityDiagnosis.create_diagnosis(
                self.job_seeker,
                author=self.request.user,
                author_prescriber_organization=self.request.current_organization,
                administrative_criteria=form.cleaned_data,
            )
            message = f"L’éligibilité du candidat {self.job_seeker.get_inverted_full_name()} a bien été validée."
        elif self.eligibility_diagnosis and not form.data.get("shrouded"):
            EligibilityDiagnosis.update_diagnosis(
                self.eligibility_diagnosis,
                author=self.request.user,
                author_prescriber_organization=self.request.current_organization,
                administrative_criteria=form.cleaned_data,
            )
            message = f"L’éligibilité du candidat {self.job_seeker.get_inverted_full_name()} a bien été mise à jour."
        if message and self.display_success_messages:
            messages.success(self.request, message, extra_tags="toast")
        return HttpResponseRedirect(self.get_success_url())

    def get_back_url(self):
        raise NotImplementedError

    def get_success_url(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["back_url"] = self.get_back_url()
        context["job_seeker"] = self.job_seeker
        context["eligibility_diagnosis"] = self.eligibility_diagnosis
        context["criteria_filled_from_job_seeker"] = self.criteria_filled_from_job_seeker
        if self.eligibility_diagnosis:
            # self.request.from_authorized_prescriber is True so the user is a prescriber
            context["new_expires_at_if_updated"] = self.eligibility_diagnosis._expiration_date(UserKind.PRESCRIBER)
        return context


class BaseIAEEligibilityViewForEmployer(UserPassesTestMixin, FormView):
    template_name = None
    form_class = AdministrativeCriteriaForm

    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        self.criteria_filled_from_job_seeker = None

    def test_func(self):
        return self.request.user.is_employer

    def dispatch(self, request, *args, **kwargs):
        if not self.company.is_subject_to_iae_rules:
            raise Http404()

        if suspension_explanation := self.company.get_active_suspension_text_with_dates():
            raise PermissionDenied(
                "Vous ne pouvez pas valider les critères d'éligibilité suite aux mesures prises dans le cadre "
                "du contrôle a posteriori. " + suspension_explanation
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_authorized_prescriber"] = False
        kwargs["siae"] = self.company
        return kwargs

    def get_cancel_url(self):
        raise NotImplementedError

    def get_initial(self):
        initial = super().get_initial()
        if self.job_seeker.last_checked_at > timezone.now() - timezone.timedelta(hours=24):
            self.criteria_filled_from_job_seeker = get_criteria_from_job_seeker(self.job_seeker)
            initial["administrative_criteria"] = self.criteria_filled_from_job_seeker
        return initial

    def form_valid(self, form):
        EligibilityDiagnosis.create_diagnosis(
            self.job_seeker,
            author=self.request.user,
            author_siae=self.request.current_organization,
            administrative_criteria=form.cleaned_data,
        )
        messages.success(self.request, "Éligibilité confirmée !", extra_tags="toast")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["job_seeker"] = self.job_seeker
        context["cancel_url"] = self.get_cancel_url()
        context["matomo_custom_title"] = "Evaluation de la candidature"
        context["criteria_filled_from_job_seeker"] = self.criteria_filled_from_job_seeker
        return context


class UpdateIAEEligibilityView(BaseIAEEligibilityViewForPrescriber):
    template_name = "eligibility/update_iae.html"
    display_success_messages = True

    def setup(self, request, *args, job_seeker_public_id, **kwargs):
        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id
        )
        self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, None)
        self.back_url = get_safe_url(request, "back_url")
        self.company = None

        super().setup(request, *args, **kwargs)

    def get_back_url(self):
        return self.back_url

    def get_success_url(self):
        return self.back_url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["matomo_custom_title"] = "Mise à jour éligibilité IAE candidat"
        return context
