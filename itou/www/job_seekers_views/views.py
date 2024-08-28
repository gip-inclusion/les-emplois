from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, DateTimeField, Exists, IntegerField, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.views.generic import DetailView, ListView

from itou.companies.enums import CompanyKind
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.pagination import ItouPaginator
from itou.utils.urls import get_safe_url

from .forms import FilterForm


class JobSeekerDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = User
    queryset = User.objects.select_related("jobseeker_profile")
    template_name = "job_seekers_views/details.html"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"
    context_object_name = "job_seeker"

    def test_func(self):
        return self.request.user.is_authenticated and (
            self.request.user.is_prescriber or self.request.user.is_employer
        )

    def get_context_data(self, **kwargs):
        geiq_eligibility_diagnosis = None
        if self.request.user.is_prescriber or (
            self.request.user.is_employer and self.request.current_organization.kind == CompanyKind.GEIQ
        ):
            geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.object,
                for_geiq=self.request.current_organization if self.request.user.is_employer else None,
            ).first()

        approval = None
        iae_eligibility_diagnosis = None
        if self.request.user.is_prescriber or (
            self.request.user.is_employer and self.request.current_organization.is_subject_to_eligibility_rules
        ):
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
            "back_url": get_safe_url(self.request, "back_url"),
            "sent_job_applications": (
                self.object.job_applications.prescriptions_of(
                    self.request.user,
                    getattr(self.request, "current_organization", None),  # job seekers have no current_organization
                )
                .select_related(
                    "to_company",
                    "sender",
                )
                .prefetch_related("selected_jobs")
            ),
            # already checked in test_func because the user name is displayed in the title
            "can_view_personal_information": self.request.user.can_view_personal_information(self.object),
            "can_edit_personal_information": self.request.user.can_edit_personal_information(self.object),
        }


class JobSeekerListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = User
    queryset = (
        User.objects.filter(kind=UserKind.JOB_SEEKER).order_by("first_name", "last_name").prefetch_related("approvals")
    )
    paginate_by = 10
    paginator_class = ItouPaginator

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.test_func():
            self.form = FilterForm(
                User.objects.filter(kind=UserKind.JOB_SEEKER).filter(Exists(self._get_user_job_applications())),
                self.request.GET or None,
            )

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_prescriber

    def get_template_names(self):
        return ["job_seekers_views/includes/list_results.html" if self.request.htmx else "job_seekers_views/list.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["back_url"] = get_safe_url(self.request, "back_url")
        context["filters_form"] = self.form
        page_obj = context["page_obj"]
        if page_obj is not None:
            for job_seeker in page_obj:
                job_seeker.user_can_view_personal_information = self.request.user.can_view_personal_information(
                    job_seeker
                )
        return context

    def _get_user_job_applications(self):
        return JobApplication.objects.prescriptions_of(self.request.user, self.request.current_organization).filter(
            job_seeker=OuterRef("pk")
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        user_applications = self._get_user_job_applications()
        subquery_count = Subquery(
            user_applications.values("job_seeker").annotate(count=Count("pk")).values("count"),
            output_field=IntegerField(),
        )
        subquery_last_update = Subquery(
            user_applications.values("job_seeker").annotate(last_update=Max("updated_at")).values("last_update"),
            output_field=DateTimeField(),
        )
        subquery_diagnosis = Subquery(
            (
                EligibilityDiagnosis.objects.valid()
                .for_job_seeker_and_siae(job_seeker=OuterRef("pk"), siae=None)
                .values("id")[:1]
            ),
            output_field=IntegerField(),
        )
        query = queryset.filter(Exists(user_applications)).annotate(
            job_applications_nb=Coalesce(subquery_count, 0),
            last_updated_at=subquery_last_update,
            valid_eligibility_diagnosis=subquery_diagnosis,
        )

        if self.form.is_valid() and (job_seeker_pk := self.form.cleaned_data["job_seeker"]):
            query = query.filter(pk=job_seeker_pk)

        return query
