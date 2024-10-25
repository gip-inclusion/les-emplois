from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, DateTimeField, Exists, IntegerField, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import DetailView, ListView

from itou.companies.enums import CompanyKind
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.gps.models import FollowUpGroup
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.pagination import ItouPaginator
from itou.utils.session import SessionNamespace
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import ApplyStepBaseView, ApplyStepForSenderBaseView

from .forms import CheckJobSeekerNirForm, FilterForm


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
            geiq_eligibility_diagnosis = (
                GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                    self.object,
                    for_geiq=self.request.current_organization if self.request.user.is_employer else None,
                )
                .prefetch_related("selected_administrative_criteria__administrative_criteria")
                .first()
            )

        approval = None
        iae_eligibility_diagnosis = None
        if self.request.user.is_prescriber or (
            self.request.user.is_employer and self.request.current_organization.is_subject_to_eligibility_rules
        ):
            approval = self.object.approvals.valid().prefetch_related("suspension_set").first()
            iae_eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.object,
                for_siae=self.request.current_organization if self.request.user.is_employer else None,
                prefetch=["selected_administrative_criteria__administrative_criteria"],
            )

        if geiq_eligibility_diagnosis:
            geiq_eligibility_diagnosis.criteria_display = geiq_eligibility_diagnosis.get_criteria_display_qs()

        if iae_eligibility_diagnosis:
            iae_eligibility_diagnosis.criteria_display = iae_eligibility_diagnosis.get_criteria_display_qs()

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


class CheckNIRForJobSeekerView(ApplyStepBaseView):
    template_name = "job_seekers_views/step_check_job_seeker_nir.html"

    def __init__(self):
        super().__init__()
        self.job_seeker = None
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.job_seeker = request.user
        self.form = CheckJobSeekerNirForm(job_seeker=self.job_seeker, data=request.POST or None)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.job_seeker.is_job_seeker:
            return HttpResponseRedirect(reverse("apply:start", kwargs={"company_pk": self.company.pk}))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # The NIR already exists, go to next step
        if self.job_seeker.jobseeker_profile.nir:
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        next_url = reverse(
            "apply:step_check_job_seeker_info",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )
        if self.form.is_valid():
            self.job_seeker.jobseeker_profile.nir = self.form.cleaned_data["nir"]
            self.job_seeker.jobseeker_profile.lack_of_nir_reason = ""
            self.job_seeker.jobseeker_profile.save()
            return HttpResponseRedirect(next_url)
        else:
            kwargs["temporary_nir_url"] = next_url

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "preview_mode": False,
        }


class CheckNIRForSenderView(ApplyStepForSenderBaseView):
    template_name = "job_seekers_views/step_check_job_seeker_nir.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CheckJobSeekerNirForm(job_seeker=None, data=request.POST or None, is_gps=self.is_gps)

    def search_by_email_url(self, session_uuid):
        view_name = "apply:search_by_email_for_hire" if self.hire_process else "apply:search_by_email_for_sender"
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "session_uuid": session_uuid}) + (
            "?gps=true" if self.is_gps else ""
        )

    def post(self, request, *args, **kwargs):
        context = {}
        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                job_seeker_session = SessionNamespace.create_temporary(request.session)
                job_seeker_session.init({"profile": {"nir": self.form.cleaned_data["nir"]}})
                return HttpResponseRedirect(self.search_by_email_url(job_seeker_session.name))

            # The NIR we found is correct
            if self.form.data.get("confirm"):
                if self.is_gps:
                    FollowUpGroup.objects.follow_beneficiary(
                        beneficiary=job_seeker, user=request.user, is_referent=True
                    )
                    return HttpResponseRedirect(reverse("gps:my_groups"))
                else:
                    return self.redirect_to_check_infos(job_seeker.public_id)

            context = {
                # Ask the sender to confirm the NIR we found is associated to the correct user
                "preview_mode": bool(self.form.data.get("preview")),
                "job_seeker": job_seeker,
                "can_view_personal_information": self.sender.can_view_personal_information(job_seeker),
            }
        else:
            # Require at least one attempt with an invalid NIR to access the search by email feature.
            # The goal is to prevent users from skipping the search by NIR and creating duplicates.
            job_seeker_session = SessionNamespace.create_temporary(request.session)
            job_seeker_session.init({})
            context["temporary_nir_url"] = self.search_by_email_url(job_seeker_session.name)

        return self.render_to_response(self.get_context_data(**kwargs) | context)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "job_seeker": None,
            "preview_mode": False,
        }
