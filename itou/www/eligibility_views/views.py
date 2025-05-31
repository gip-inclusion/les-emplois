from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView

from itou.companies.models import Company
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.session import SessionNamespace
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import APPLY_SESSION_KIND, JOB_SEEKER_INFOS_CHECK_PERIOD
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


class UpdateEligibilityView(UserPassesTestMixin, FormView):
    template_name = "eligibility/update.html"
    form_class = AdministrativeCriteriaForm
    standalone_process = None
    prescription_process = None
    apply_session = None

    def setup(self, request, *args, job_seeker_public_id=None, tunnel=None, session_uuid=None, **kwargs):
        super().setup(request, *args, **kwargs)

        if tunnel not in ("standalone_process", "prescription_process"):
            raise Http404
        setattr(self, tunnel, True)

        self.company = None
        if self.prescription_process:
            self.apply_session = SessionNamespace(request.session, APPLY_SESSION_KIND, session_uuid)
            if not self.apply_session.exists():
                raise Http404
            self.company = get_object_or_404(Company.objects, pk=self.apply_session.get("company_pk"))
            job_seeker_public_id = self.apply_session.get("job_seeker_public_id")

        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id
        )
        self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, self.company)

    def test_func(self):
        if self.standalone_process:
            return self.request.from_authorized_prescriber
        if self.prescription_process:
            # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
            return self.company.is_subject_to_eligibility_rules and self.request.from_authorized_prescriber
        return False

    def dispatch(self, request, *args, **kwargs):
        # No need for eligibility diagnosis if the job seeker already has a PASS IAE
        if self.job_seeker.approvals.valid().exists():
            return HttpResponseRedirect(self.get_success_url())
        if self.company and not self.company.is_subject_to_eligibility_rules:
            # We should not have arrived here, but just dispatch to next url
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
            if self.standalone_process:
                message = f"L’éligibilité du candidat {self.job_seeker.get_full_name()} a bien été validée."
        elif self.eligibility_diagnosis and not form.data.get("shrouded"):
            EligibilityDiagnosis.update_diagnosis(
                self.eligibility_diagnosis,
                author=self.request.user,
                author_organization=self.request.current_organization,
                administrative_criteria=form.cleaned_data,
            )
            if self.standalone_process:
                message = f"L’éligibilité du candidat {self.job_seeker.get_full_name()} a bien été mise à jour."
        if message:
            messages.success(self.request, message, extra_tags="toast")
        return HttpResponseRedirect(self.get_success_url())

    def get_back_url(self):
        back_url = None
        if self.standalone_process:
            back_url = get_safe_url(self.request, "back_url")
        if self.prescription_process:
            back_url = reverse("apply:application_jobs", kwargs={"session_uuid": self.apply_session.name})
        # Force developpers to always provide a proper back_url
        if back_url:
            return back_url
        raise Http404

    def get_success_url(self):
        if self.standalone_process:
            return self.get_back_url()
        if self.prescription_process:
            return reverse("apply:application_resume", kwargs={"session_uuid": self.apply_session.name})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "back_url": self.get_back_url(),
                "job_seeker": self.job_seeker,
                "eligibility_diagnosis": self.eligibility_diagnosis,
                "standalone_process": self.standalone_process,
                "prescription_process": self.prescription_process,
                "company": self.company,
                "can_view_personal_information": can_view_personal_information(self.request, self.job_seeker),
            }
        )
        if self.eligibility_diagnosis:
            context["new_expires_at_if_updated"] = self.eligibility_diagnosis._expiration_date(self.request.user)
        if self.prescription_process:
            context.update(
                {
                    "progress": 50,
                    "full_content_width": True,
                    "reset_url": self.apply_session.get("reset_url", reverse("dashboard:index")),
                    "is_subject_to_eligibility_rules": True,  # Used to display the eligibility badge in the title
                    "new_check_needed": (
                        self.job_seeker.last_checked_at < timezone.now() - JOB_SEEKER_INFOS_CHECK_PERIOD
                    ),
                    "hire_process": None,  # because of "apply/includes/_submit_title.html"
                    "auto_prescription_process": None,  # because of "apply/includes/_submit_title.html"
                }
            )
            # Do we need new_check_needed alert ?
        return context
