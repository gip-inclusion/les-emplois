import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, DateTimeField, Exists, IntegerField, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.generic import DetailView, ListView, TemplateView

from itou.companies import enums as companies_enums
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.gps.models import FollowUpGroup
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis.exceptions import AddressLookupError
from itou.utils.emails import redact_email_address
from itou.utils.pagination import ItouPaginator
from itou.utils.session import SessionNamespace, SessionNamespaceRequiredMixin
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import ApplicationBaseView, ApplyStepBaseView, ApplyStepForSenderBaseView

from .forms import (
    CheckJobSeekerInfoForm,
    CheckJobSeekerNirForm,
    CreateOrUpdateJobSeekerStep1Form,
    CreateOrUpdateJobSeekerStep2Form,
    CreateOrUpdateJobSeekerStep3Form,
    FilterForm,
    JobSeekerExistsForm,
)


logger = logging.getLogger(__name__)


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


class JobSeekerBaseView(LoginRequiredMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.company = None
        self.job_seeker_session = None
        self.hire_process = None
        self.prescription_proces = None
        self.auto_prescription_process = None
        self.is_gps = False

    def setup(self, request, *args, session_uuid, hire_process=False, **kwargs):
        self.job_seeker_session = SessionNamespace(request.session, session_uuid)
        if not self.job_seeker_session.exists():
            raise Http404
        self.is_gps = "gps" in request.GET and request.GET["gps"] == "true"
        # TODO(ewen): temporary condition to fill self.company when not using the new session system
        if company_pk := kwargs.get("company_pk"):
            self.job_seeker_session.set("apply", {"company_pk": company_pk} | self.job_seeker_session.get("apply", {}))
        if company_pk := self.job_seeker_session.get("apply", {}).get("company_pk"):
            self.company = (
                get_object_or_404(Company.objects.with_has_active_members(), pk=company_pk)
                if not self.is_gps
                else Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)
            )
        self.hire_process = hire_process
        self.prescription_process = (
            not self.hire_process
            and not self.is_gps
            and request.user.is_authenticated
            and (
                request.user.is_prescriber
                or (request.user.is_employer and self.company != request.current_organization)
            )
        )
        self.auto_prescription_process = (
            not self.hire_process
            and not self.is_gps
            and request.user.is_authenticated
            and request.user.is_employer
            and self.company == request.current_organization
        )

        super().setup(request, *args, **kwargs)

    def redirect_to_check_infos(self, job_seeker_public_id):
        view_name = (
            "job_seekers_views:check_job_seeker_info_for_hire"
            if self.hire_process
            else "job_seekers_views:check_job_seeker_info"
        )
        return HttpResponseRedirect(
            reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": job_seeker_public_id})
        )

    def get_back_url(self):
        return None

    def get_reset_url(self):
        return self.job_seeker_session.get("config", {}).get("reset_url") or reverse("dashboard:index")

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "siae": self.company,
            "back_url": self.get_back_url(),
            "reset_url": self.get_reset_url(),
            "hire_process": self.hire_process,
            "prescription_process": self.prescription_process,
            "auto_prescription_process": self.auto_prescription_process,
            "is_gps": self.is_gps,
        }


class JobSeekerForSenderBaseView(JobSeekerBaseView):
    def __init__(self):
        super().__init__()
        self.sender = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if self.sender.is_authenticated and self.sender.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            logger.info(f"dispatch ({request.path}) : {self.sender.kind} in sender tunnel")
            return HttpResponseRedirect(reverse("apply:start", kwargs={"company_pk": self.company.pk}))
        return super().dispatch(request, *args, **kwargs)


class DeprecatedCheckNIRForJobSeekerView(ApplyStepBaseView):
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
            logger.info(f"dispatch ({request.path}) : {request.user.kind} in jobseeker tunnel")
            return HttpResponseRedirect(reverse("apply:start", kwargs={"company_pk": self.company.pk}))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # The NIR already exists, go to next step
        if self.job_seeker.jobseeker_profile.nir:
            return HttpResponseRedirect(
                reverse(
                    "job_seekers_views:check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        next_url = reverse(
            "job_seekers_views:check_job_seeker_info",
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


class CheckNIRForJobSeekerView(JobSeekerBaseView):
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
            logger.info(f"dispatch ({request.path}) : {request.user.kind} in jobseeker tunnel")
            return HttpResponseRedirect(reverse("apply:start", kwargs={"company_pk": self.company.pk}))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # The NIR already exists, go to next step
        if self.job_seeker.jobseeker_profile.nir:
            return HttpResponseRedirect(
                reverse(
                    "job_seekers_views:check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker.jobseeker_profile.nir = self.form.cleaned_data["nir"]
            self.job_seeker.jobseeker_profile.lack_of_nir_reason = ""
            self.job_seeker.jobseeker_profile.save(update_fields=("nir", "lack_of_nir_reason"))
            return self.redirect_to_check_infos(self.job_seeker.public_id)
        else:
            next_url = reverse(
                "job_seekers_views:check_job_seeker_info",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            )
            kwargs["temporary_nir_url"] = next_url

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "preview_mode": False,
        }


class DeprecatedCheckNIRForSenderView(ApplyStepForSenderBaseView):
    template_name = "job_seekers_views/step_check_job_seeker_nir.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CheckJobSeekerNirForm(job_seeker=None, data=request.POST or None, is_gps=self.is_gps)

    def search_by_email_url(self, session_uuid):
        view_name = (
            "job_seekers_views:search_by_email_for_hire"
            if self.hire_process
            else "job_seekers_views:search_by_email_for_sender"
        )
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "session_uuid": session_uuid}) + (
            "?gps=true" if self.is_gps else ""
        )

    def post(self, request, *args, **kwargs):
        context = {}
        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                job_seeker_session = SessionNamespace.create_uuid_namespace(
                    request.session, data={"profile": {"nir": self.form.cleaned_data["nir"]}}
                )
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
            job_seeker_session = SessionNamespace.create_uuid_namespace(request.session, data={})
            context["temporary_nir_url"] = self.search_by_email_url(job_seeker_session.name)

        return self.render_to_response(self.get_context_data(**kwargs) | context)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "job_seeker": None,
            "preview_mode": False,
        }


class CheckNIRForSenderView(JobSeekerForSenderBaseView):
    template_name = "job_seekers_views/step_check_job_seeker_nir.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CheckJobSeekerNirForm(job_seeker=None, data=request.POST or None, is_gps=self.is_gps)

    def search_by_email_url(self, session_uuid):
        view_name = (
            "job_seekers_views:search_by_email_for_hire"
            if self.hire_process
            else "job_seekers_views:search_by_email_for_sender"
        )
        return reverse(view_name, kwargs={"session_uuid": session_uuid}) + ("?gps=true" if self.is_gps else "")

    def post(self, request, *args, **kwargs):
        context = {}

        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                self.job_seeker_session.set("profile", {"nir": self.form.cleaned_data["nir"]})
                return HttpResponseRedirect(self.search_by_email_url(self.job_seeker_session.name))

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
            context["temporary_nir_url"] = self.search_by_email_url(self.job_seeker_session.name)

        return self.render_to_response(self.get_context_data(**kwargs) | context)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "job_seeker": None,
            "preview_mode": False,
        }


class SearchByEmailForSenderView(SessionNamespaceRequiredMixin, JobSeekerForSenderBaseView):
    required_session_namespaces = ["job_seeker_session"]
    template_name = "job_seekers_views/step_search_job_seeker_by_email.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = JobSeekerExistsForm(
            is_gps=self.is_gps, initial=self.job_seeker_session.get("user", {}), data=request.POST or None
        )

    def post(self, request, *args, **kwargs):
        can_add_nir = False
        preview_mode = False
        job_seeker = None

        if self.form.is_valid():
            job_seeker = self.form.get_user()
            nir = self.job_seeker_session.get("profile", {}).get("nir")
            can_add_nir = nir and self.sender.can_add_nir(job_seeker)

            # No user found with that email, redirect to create a new account.
            if not job_seeker:
                user_infos = self.job_seeker_session.get("user", {})
                user_infos.update({"email": self.form.cleaned_data["email"]})
                profile_infos = self.job_seeker_session.get("profile", {})
                profile_infos.update({"nir": nir})
                self.job_seeker_session.update({"user": user_infos, "profile": profile_infos})
                view_name = (
                    "job_seekers_views:create_job_seeker_step_1_for_hire"
                    if self.hire_process
                    else "job_seekers_views:create_job_seeker_step_1_for_sender"
                )

                return HttpResponseRedirect(
                    reverse(view_name, kwargs={"session_uuid": self.job_seeker_session.name})
                    + ("?gps=true" if self.is_gps else "")
                )

            # Ask the sender to confirm the email we found is associated to the correct user
            if self.form.data.get("preview"):
                preview_mode = True

            # The email we found is correct
            if self.form.data.get("confirm"):
                if not can_add_nir:
                    return self.redirect_to_check_infos(job_seeker.public_id)

                try:
                    job_seeker.jobseeker_profile.nir = nir
                    job_seeker.jobseeker_profile.lack_of_nir_reason = ""
                    job_seeker.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])
                except ValidationError:
                    msg = format_html(
                        "Le<b> numéro de sécurité sociale</b> renseigné ({}) est "
                        "déjà utilisé par un autre candidat sur la Plateforme.<br>"
                        "Merci de renseigner <b>le numéro personnel et unique</b> "
                        "du candidat pour lequel vous souhaitez postuler.",
                        nir,
                    )
                    messages.warning(request, msg)
                    logger.exception("step_job_seeker: error when saving job_seeker=%s nir=%s", job_seeker, nir)
                else:
                    if self.is_gps:
                        FollowUpGroup.objects.follow_beneficiary(
                            beneficiary=job_seeker, user=request.user, is_referent=True
                        )
                        return HttpResponseRedirect(reverse("gps:my_groups"))
                    else:
                        return self.redirect_to_check_infos(job_seeker.public_id)

        return self.render_to_response(
            self.get_context_data(**kwargs)
            | {
                "can_add_nir": can_add_nir,
                "preview_mode": preview_mode,
                "job_seeker": job_seeker,
                "can_view_personal_information": job_seeker and self.sender.can_view_personal_information(job_seeker),
            }
        )

    def get_back_url(self):
        view_name = (
            "job_seekers_views:check_nir_for_hire" if self.hire_process else "job_seekers_views:check_nir_for_sender"
        )
        return reverse(view_name, kwargs={"session_uuid": self.job_seeker_session.name})

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "nir": self.job_seeker_session.get("profile", {}).get("nir"),
            "siae": self.company,
            "preview_mode": False,
        }


class CreateJobSeekerForSenderBaseView(JobSeekerForSenderBaseView):
    required_session_namespaces = ["job_seeker_session"]

    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def get_back_url(self):
        view_name = self.previous_hire_url if self.hire_process else self.previous_apply_url
        return reverse(
            view_name,
            kwargs={"session_uuid": self.job_seeker_session.name},
        ) + ("?gps=true" if self.is_gps else "")

    def get_next_url(self):
        view_name = self.next_hire_url if self.hire_process else self.next_apply_url
        return reverse(
            view_name,
            kwargs={"session_uuid": self.job_seeker_session.name},
        ) + ("?gps=true" if self.is_gps else "")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["update_job_seeker"] = False
        context["readonly_form"] = False
        return context


class CreateJobSeekerStep1ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_1.html"

    previous_apply_url = "job_seekers_views:search_by_email_for_sender"
    previous_hire_url = "job_seekers_views:search_by_email_for_hire"
    next_apply_url = "job_seekers_views:create_job_seeker_step_2_for_sender"
    next_hire_url = "job_seekers_views:create_job_seeker_step_2_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        session_birthdate = self.job_seeker_session.get("profile", {}).get(
            "birthdate", self.job_seeker_session.get("user", {}).get("birthdate")
        )  # TODO(xfernandez): drop fallback on self.job_seeker_session["user"] in a week
        session_nir = self.job_seeker_session.get("profile", {}).get("nir")
        session_lack_of_nir_reason = self.job_seeker_session.get("profile", {}).get("lack_of_nir_reason")
        session_birth_place = self.job_seeker_session.get("profile", {}).get("birth_place")
        session_birth_country = self.job_seeker_session.get("profile", {}).get("birth_country")

        self.form = CreateOrUpdateJobSeekerStep1Form(
            data=request.POST or None,
            initial=self.job_seeker_session.get("user", {})
            | {
                "birthdate": session_birthdate,
                "nir": session_nir,
                "lack_of_nir_reason": session_lack_of_nir_reason,
                "birth_place": session_birth_place,
                "birth_country": session_birth_country,
            },
        )

    def post(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        context["confirmation_needed"] = False
        if self.form.is_valid():
            existing_job_seeker = User.objects.filter(
                kind=UserKind.JOB_SEEKER,
                jobseeker_profile__birthdate=self.form.cleaned_data["birthdate"],
                first_name__unaccent__iexact=self.form.cleaned_data["first_name"],
                last_name__unaccent__iexact=self.form.cleaned_data["last_name"],
            ).first()
            if existing_job_seeker and not self.form.data.get("confirm"):
                # If an existing job seeker matches the info, a confirmation is required
                context["confirmation_needed"] = True
                context["redacted_existing_email"] = redact_email_address(existing_job_seeker.email)
                context["email_to_create"] = self.job_seeker_session.get("user", {}).get("email", "")

            if not context["confirmation_needed"]:
                self.job_seeker_session.set(
                    "user",
                    self.job_seeker_session.get("user", {}) | self.form.cleaned_data_without_profile_fields,
                )
                self.job_seeker_session.set(
                    "profile",
                    self.job_seeker_session.get("profile", {}) | self.form.cleaned_data_from_profile_fields,
                )
                return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(context)

    # TODO(ewen): remove this method overloading when migration is over
    def get_back_url(self):
        view_name = self.previous_hire_url if self.hire_process else self.previous_apply_url
        kwargs = {"session_uuid": self.job_seeker_session.name}
        if not self.job_seeker_session.get("apply", {}).get("company_pk"):
            kwargs["company_pk"] = self.company.pk
        return reverse(view_name, kwargs=kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "matomo_form_name": "apply-create-job-seeker-identity",
            "progress": "20",
        }


class CreateJobSeekerStep2ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_2.html"

    previous_apply_url = "job_seekers_views:create_job_seeker_step_1_for_sender"
    previous_hire_url = "job_seekers_views:create_job_seeker_step_1_for_hire"
    next_apply_url = "job_seekers_views:create_job_seeker_step_3_for_sender"
    next_hire_url = "job_seekers_views:create_job_seeker_step_3_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CreateOrUpdateJobSeekerStep2Form(
            data=request.POST or None, initial=self.job_seeker_session.get("user", {})
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker_session.set("user", self.job_seeker_session.get("user") | self.form.cleaned_data)
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "40",
        }


class CreateJobSeekerStep3ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_3.html"

    previous_apply_url = "job_seekers_views:create_job_seeker_step_2_for_sender"
    previous_hire_url = "job_seekers_views:create_job_seeker_step_2_for_hire"
    next_apply_url = "job_seekers_views:create_job_seeker_step_end_for_sender"
    next_hire_url = "job_seekers_views:create_job_seeker_step_end_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = CreateOrUpdateJobSeekerStep3Form(
            data=request.POST or None,
            initial=self.job_seeker_session.get("profile", {}),
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker_session.set("profile", self.job_seeker_session.get("profile", {}) | self.form.cleaned_data)
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "60",
        }


class CreateJobSeekerStepEndForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_end.html"

    previous_apply_url = "job_seekers_views:create_job_seeker_step_3_for_sender"
    previous_hire_url = "job_seekers_views:create_job_seeker_step_3_for_hire"
    next_apply_url = "apply:application_jobs"
    next_hire_url = None  # Depends on GEIQ/non-GEIQ

    def __init__(self):
        super().__init__()
        self.profile = None

    def _get_user_data_from_session(self):
        return {
            k: v
            for k, v in self.job_seeker_session.get("user").items()
            if k
            not in [
                "lack_of_nir",
                # Address autocomplete fields
                "fill_mode",
                "address_for_autocomplete",
                "insee_code",
                # TODO(xfernandez): remove birthdate in a week
                "birthdate",
            ]
        }

    def _get_profile_data_from_session(self):
        fields_to_exclude = [
            # Dummy fields used by CreateOrUpdateJobSeekerStep3Form()
            "pole_emploi",
            "pole_emploi_id_forgotten",
            "rsa_allocation",
            "unemployed",
            "ass_allocation",
            "aah_allocation",
            "lack_of_nir",
            # ForeignKeys - the session value will be the ID serialization and not the instance
            "birth_place",
            "birth_country",
        ]

        birth_data = {
            "birth_place_id": self.job_seeker_session.get("profile", {}).get("birth_place"),
            "birth_country_id": self.job_seeker_session.get("profile", {}).get("birth_country"),
        }

        # TODO(xfernandez): remove user session birthdate handling in a week
        if birthdate_from_user_session := self.job_seeker_session.get("user", {}).get("birthdate"):
            birth_data |= {"birthdate": birthdate_from_user_session}

        return birth_data | {
            k: v for k, v in self.job_seeker_session.get("profile").items() if k not in fields_to_exclude
        }

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.profile = JobSeekerProfile(
            user=User(**self._get_user_data_from_session()),
            **self._get_profile_data_from_session(),
        )

    def get_next_url(self):
        kwargs = {"company_pk": self.company.pk, "job_seeker_public_id": self.profile.user.public_id}

        if self.is_gps:
            kwargs = {}
            view_name = "gps:my_groups"
        elif self.hire_process:
            if self.company.kind == CompanyKind.GEIQ:
                view_name = "apply:geiq_eligibility_for_hire"
            else:
                view_name = "apply:eligibility_for_hire"
        else:
            view_name = self.next_apply_url

        return reverse(
            view_name,
            kwargs=kwargs,
        )

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                user = User.create_job_seeker_by_proxy(
                    self.sender, **self._get_user_data_from_session(), acting_organization=request.current_organization
                )
                self.profile = user.jobseeker_profile
                for k, v in self._get_profile_data_from_session().items():
                    setattr(self.profile, k, v)
                self.profile.save()
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            url = reverse("dashboard:index")
        else:
            try:
                user.geocode_address()
            except AddressLookupError:
                # Nothing to do: re-raised and already logged as error
                pass
            else:
                user.save()

            self.job_seeker_session.delete()
            url = self.get_next_url()

            if self.is_gps:
                FollowUpGroup.objects.follow_beneficiary(beneficiary=user, user=request.user, is_referent=True)

        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {"profile": self.profile, "progress": "80"}


class UpdateJobSeekerBaseView(SessionNamespaceRequiredMixin, ApplyStepBaseView):
    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def get_job_seeker_queryset(self):
        return User.objects.filter(kind=UserKind.JOB_SEEKER)

    def setup(self, request, *args, **kwargs):
        self.job_seeker = get_object_or_404(self.get_job_seeker_queryset(), public_id=kwargs["job_seeker_public_id"])
        self.job_seeker_session = SessionNamespace(request.session, f"job_seeker-{self.job_seeker.public_id}")
        if request.user.is_authenticated and (
            request.user.is_job_seeker or not request.user.can_view_personal_information(self.job_seeker)
        ):
            # Since the link leading to this process isn't visible to those users, this should never happen
            raise PermissionDenied("Votre utilisateur n'est pas autorisé à vérifier les informations de ce candidat")
        super().setup(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "update_job_seeker": True,
            "job_seeker": self.job_seeker,
            "step_3_url": reverse(
                "job_seekers_views:update_job_seeker_step_3_for_hire"
                if self.hire_process
                else "job_seekers_views:update_job_seeker_step_3",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            ),
            "reset_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            ),
            "readonly_form": False,
        }

    def _disable_form(self):
        for field in self.form:
            field.field.disabled = True

    def get_back_url(self):
        view_name = self.previous_hire_url if self.hire_process else self.previous_apply_url
        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )

    def get_next_url(self):
        view_name = self.next_hire_url if self.hire_process else self.next_apply_url
        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )


class UpdateJobSeekerStep1View(UpdateJobSeekerBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_1.html"

    previous_apply_url = "apply:application_jobs"
    previous_hire_url = "job_seekers_views:check_job_seeker_info_for_hire"
    next_apply_url = "job_seekers_views:update_job_seeker_step_2"
    next_hire_url = "job_seekers_views:update_job_seeker_step_2_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def get_job_seeker_queryset(self):
        return super().get_job_seeker_queryset().select_related("jobseeker_profile")

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return
        if not self.job_seeker_session.exists():
            self.job_seeker_session.init({"user": {}})
        session_nir = self.job_seeker_session.get("profile", {}).get("nir")
        session_lack_of_nir_reason = self.job_seeker_session.get("profile", {}).get("lack_of_nir_reason")

        self.form = CreateOrUpdateJobSeekerStep1Form(
            instance=self.job_seeker,
            initial=self.job_seeker_session.get("user", {})
            | {
                "nir": session_nir if session_nir is not None else self.job_seeker.jobseeker_profile.nir,
                "lack_of_nir_reason": (
                    session_lack_of_nir_reason
                    if session_lack_of_nir_reason is not None
                    else self.job_seeker.jobseeker_profile.lack_of_nir_reason
                ),
            },
            data=request.POST or None,
        )
        if not self.request.user.can_edit_personal_information(self.job_seeker):
            self._disable_form()

    def post(self, request, *args, **kwargs):
        if not self.request.user.can_edit_personal_information(self.job_seeker):
            return HttpResponseRedirect(self.get_next_url())
        if self.form.is_valid():
            self.job_seeker_session.set(
                "user",
                self.job_seeker_session.get("user", {}) | self.form.cleaned_data_without_profile_fields,
            )
            self.job_seeker_session.set(
                "profile",
                self.job_seeker_session.get("profile", {}) | self.form.cleaned_data_from_profile_fields,
            )
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "confirmation_needed": False,
            "form": self.form,
            "matomo_form_name": "apply-update-job-seeker-identity",
            "readonly_form": not self.request.user.can_edit_personal_information(self.job_seeker),
            "progress": "20",
        }


class UpdateJobSeekerStep2View(UpdateJobSeekerBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_2.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

    previous_apply_url = "job_seekers_views:update_job_seeker_step_1"
    previous_hire_url = "job_seekers_views:update_job_seeker_step_1_for_hire"
    next_apply_url = "job_seekers_views:update_job_seeker_step_3"
    next_hire_url = "job_seekers_views:update_job_seeker_step_3_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CreateOrUpdateJobSeekerStep2Form(
            instance=self.job_seeker,
            initial=self.job_seeker_session.get("user", {}),
            data=request.POST or None,
        )
        if not self.request.user.can_edit_personal_information(self.job_seeker):
            self._disable_form()

    def post(self, request, *args, **kwargs):
        if not self.request.user.can_edit_personal_information(self.job_seeker):
            return HttpResponseRedirect(self.get_next_url())
        if self.form.is_valid():
            self.job_seeker_session.set("user", self.job_seeker_session.get("user") | self.form.cleaned_data)
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "readonly_form": not self.request.user.can_edit_personal_information(self.job_seeker),
            "progress": "40",
        }


class UpdateJobSeekerStep3View(UpdateJobSeekerBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_3.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

    previous_apply_url = "job_seekers_views:update_job_seeker_step_2"
    previous_hire_url = "job_seekers_views:update_job_seeker_step_2_for_hire"
    next_apply_url = "job_seekers_views:update_job_seeker_step_end"
    next_hire_url = "job_seekers_views:update_job_seeker_step_end_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def get_job_seeker_queryset(self):
        return super().get_job_seeker_queryset().select_related("jobseeker_profile")

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        session_pole_emploi_id = self.job_seeker_session.get("profile", {}).get("pole_emploi_id")
        session_lack_of_pole_emploi_id_reason = self.job_seeker_session.get("profile", {}).get(
            "lack_of_pole_emploi_id_reason"
        )
        initial_form_data = self.job_seeker_session.get("profile", {}) | {
            "pole_emploi_id": (
                session_pole_emploi_id
                if session_pole_emploi_id is not None
                else self.job_seeker.jobseeker_profile.pole_emploi_id
            ),
            "lack_of_pole_emploi_id_reason": (
                session_lack_of_pole_emploi_id_reason
                if session_lack_of_pole_emploi_id_reason is not None
                else self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason
            ),
        }
        self.form = CreateOrUpdateJobSeekerStep3Form(
            instance=self.job_seeker.jobseeker_profile if self.job_seeker.has_jobseeker_profile else None,
            initial=initial_form_data,
            data=request.POST or None,
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker_session.set("profile", self.job_seeker_session.get("profile", {}) | self.form.cleaned_data)
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "60",
        }


class UpdateJobSeekerStepEndView(UpdateJobSeekerBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_end.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

    previous_apply_url = "job_seekers_views:update_job_seeker_step_3"
    previous_hire_url = "job_seekers_views:update_job_seeker_step_3_for_hire"
    next_apply_url = "apply:application_jobs"
    next_hire_url = "job_seekers_views:check_job_seeker_info_for_hire"

    def __init__(self):
        super().__init__()
        self.profile = None
        self.updated_user_fields = []

    def _get_profile_data_from_session(self):
        fields_to_exclude = [
            # Dummy fields used by CreateOrUpdateJobSeekerStep3Form()
            "pole_emploi",
            "pole_emploi_id_forgotten",
            "rsa_allocation",
            "unemployed",
            "ass_allocation",
            "aah_allocation",
            "lack_of_nir",
            # ForeignKeys - the session value will be the ID serialization and not the instance
            "birth_place",
            "birth_country",
        ]

        birth_data = {
            "birth_place_id": self.job_seeker_session.get("profile", {}).get("birth_place"),
            "birth_country_id": self.job_seeker_session.get("profile", {}).get("birth_country"),
        }

        return birth_data | {
            k: v for k, v in self.job_seeker_session.get("profile", {}).items() if k not in fields_to_exclude
        }

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        allowed_user_fields_to_update = []
        if self.request.user.can_edit_personal_information(self.job_seeker):
            allowed_user_fields_to_update.extend(CreateOrUpdateJobSeekerStep1Form.Meta.fields)
            allowed_user_fields_to_update.extend(CreateOrUpdateJobSeekerStep2Form.Meta.fields)

        for field in allowed_user_fields_to_update:
            if field in self.job_seeker_session.get("user", {}):
                session_value = self.job_seeker_session.get("user")[field]
                if session_value != getattr(self.job_seeker, field):
                    setattr(self.job_seeker, field, session_value)
                    self.updated_user_fields.append(field)

        if not self.job_seeker.has_jobseeker_profile:
            self.profile = JobSeekerProfile(
                user=self.job_seeker,
                **self._get_profile_data_from_session(),
            )
        else:
            self.profile = self.job_seeker.jobseeker_profile
            for k, v in self._get_profile_data_from_session().items():
                setattr(self.profile, k, v)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.updated_user_fields.append("last_checked_at")
        try:
            if "address_line_1" in self.updated_user_fields or "post_code" in self.updated_user_fields:
                try:
                    self.job_seeker.geocode_address()
                except AddressLookupError:
                    # Nothing to do: re-raised and already logged as error
                    pass
                else:
                    self.updated_user_fields.extend(["coords", "geocoding_score"])
            self.job_seeker.last_checked_at = timezone.now()
            self.job_seeker.save(update_fields=self.updated_user_fields)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            url = reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            )
        else:
            self.profile.save()
            self.job_seeker_session.delete()
            url = self.get_next_url()
        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {"profile": self.profile, "progress": "80"}


class CheckJobSeekerInformations(ApplicationBaseView):
    """
    Ensure the job seeker has all required info.
    """

    template_name = "job_seekers_views/check_job_seeker_info.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = CheckJobSeekerInfoForm(instance=self.job_seeker, data=request.POST or None)

    def get(self, request, *args, **kwargs):
        # Check required info that will allow us to find a pre-existing approval.
        has_required_info = self.job_seeker.jobseeker_profile.birthdate and (
            self.job_seeker.jobseeker_profile.pole_emploi_id
            or self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason
        )
        if has_required_info:
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_prev_applications",
                    kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.form.save()
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_prev_applications",
                    kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
        }


class CheckJobSeekerInformationsForHire(ApplicationBaseView):
    """
    Ensure the job seeker has all required info.
    """

    template_name = "job_seekers_views/check_job_seeker_info_for_hire.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        assert self.hire_process

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.job_seeker.jobseeker_profile,
            "back_url": reverse("apply:start_hire", kwargs={"company_pk": self.company.pk}),
        }
