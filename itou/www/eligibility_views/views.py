from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.generic import FormView

from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.urls import get_safe_url
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


class UpdateEligibilityView(UserPassesTestMixin, FormView):
    template_name = "eligibility/update.html"
    form_class = AdministrativeCriteriaForm
    standalone = None

    def setup(self, request, *args, job_seeker_public_id, **kwargs):
        super().setup(request, *args, **kwargs)

        # FIXME: Add more tunnels
        self.standalone = True

        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id
        )

        # FIXME: in other tunnels we need the company
        self.company = None

        self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, self.company)

    def test_func(self):
        if self.standalone:
            return self.request.from_authorized_prescriber
        return False

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
        return initial

    def form_valid(self, form):
        message = None
        if not self.eligibility_diagnosis:
            EligibilityDiagnosis.create_diagnosis(
                self.job_seeker,
                author=self.request.user,
                author_organization=self.request.current_organization,
                administrative_criteria=form.cleaned_data,
            )
            if self.standalone:
                message = f"L’éligibilité du candidat {self.job_seeker.get_full_name()} a bien été validée."
        elif self.eligibility_diagnosis and not form.data.get("shrouded"):
            EligibilityDiagnosis.update_diagnosis(
                self.eligibility_diagnosis,
                author=self.request.user,
                author_organization=self.request.current_organization,
                administrative_criteria=form.cleaned_data,
            )
            if self.standalone:
                message = f"L’éligibilité du candidat {self.job_seeker.get_full_name()} a bien été mise à jour."
        if message:
            messages.success(self.request, message, extra_tags="toast")
        return HttpResponseRedirect(self.get_success_url())

    def get_back_url(self):
        back_url = None
        if self.standalone:
            back_url = get_safe_url(self.request, "back_url")
        # Force developpers to always provide a proper back_url
        if back_url:
            return back_url
        raise Http404

    def get_success_url(self):
        # FIXME: it depends on the tunnel
        if self.standalone:
            return self.get_back_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "back_url": self.get_back_url(),
                "job_seeker": self.job_seeker,
                "eligibility_diagnosis": self.eligibility_diagnosis,
            }
        )

        if self.eligibility_diagnosis:
            context["new_expires_at_if_updated"] = self.eligibility_diagnosis._expiration_date(self.request.user)
        return context
