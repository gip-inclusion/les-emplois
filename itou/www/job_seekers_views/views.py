import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, DateTimeField, Exists, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.forms import ValidationError
from django.http import HttpResponseRedirect
from django.urls import reverse
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
from itou.utils.emails import (
    redact_email_address,
)
from itou.utils.pagination import ItouPaginator
from itou.utils.session import SessionNamespace, SessionNamespaceRequiredMixin
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    CheckJobSeekerNirForm,
    CreateOrUpdateJobSeekerStep1Form,
    CreateOrUpdateJobSeekerStep2Form,
    CreateOrUpdateJobSeekerStep3Form,
    JobSeekerExistsForm,
)

from .forms import FilterForm


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
        User.objects.filter(kind=UserKind.JOB_SEEKER)
        .order_by("first_name", "last_name")
        .prefetch_related("approvals")
        .select_related("jobseeker_profile")
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
        filter_job_seekers_created_by_org = (
            Q(jobseeker_profile__created_by_company=self.request.current_organization)
            if self.request.user.is_employer
            else Q(jobseeker_profile__created_by_prescriber_organization=self.request.current_organization)
        )
        query = queryset.filter(Q(Exists(user_applications)) | filter_job_seekers_created_by_org).annotate(
            job_applications_nb=Coalesce(subquery_count, 0),
            last_updated_at=subquery_last_update,
            valid_eligibility_diagnosis=subquery_diagnosis,
        )

        if self.form.is_valid() and (job_seeker_pk := self.form.cleaned_data["job_seeker"]):
            query = query.filter(pk=job_seeker_pk)

        return query


class CreateJobSeekerStepBaseView(LoginRequiredMixin, SessionNamespaceRequiredMixin, TemplateView):
    required_session_namespaces = ["job_seeker_session"]

    def __init__(self):
        super().__init__()
        self.job_seeker_session = None
        self.company = None
        self.is_gps = False

    def setup(self, request, *args, **kwargs):
        if session_uuid := kwargs.get("session_uuid"):
            self.job_seeker_session = SessionNamespace(request.session, session_uuid)
        else:
            self.job_seeker_session = SessionNamespace.create_temporary(request.session)
            self.job_seeker_session.init({})

        # Information fed into the session by GET parameters
        if reset_url := request.GET.get("reset_url"):
            self.job_seeker_session.update({"reset_url": reset_url})
        if parent_process := request.GET.get("parent_process"):
            self.job_seeker_session.update({"parent_process": parent_process})
        if company := request.GET.get("company"):
            self.job_seeker_session.update({"company": company})
        if job_description := request.GET.get("job_description"):
            self.job_seeker_session.update({"job_description": job_description})

        self.is_gps = "gps" in request.GET and request.GET["gps"] == "true"
        self.company = (
            Company.objects.with_has_active_members().filter(pk=self.job_seeker_session.get("company", None)).first()
            or None
            if not self.is_gps
            else Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)
        )

        super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if not self.is_gps:
            if request.user.is_authenticated:
                if request.user.kind not in [
                    UserKind.JOB_SEEKER,
                    UserKind.PRESCRIBER,
                    UserKind.EMPLOYER,
                ]:
                    raise PermissionDenied("Vous n'êtes pas autorisé à créer de compte candidat.")

        return super().dispatch(request, *args, **kwargs)

    def get_reset_url(self):
        if reset_url := self.job_seeker_session.get("reset_url"):
            return reset_url
        return None

    def get_back_url(self):
        return None

    def get_end_url(self):
        if self.job_seeker_session.get("apply_for_sender") == "apply_for":
            return "apply"
        elif self.job_seeker_session.get("apply_for_sender") == "create_from_job_seekers_list":
            return reverse("job_seekers_views:list")

    def get_context_data(self, **kwargs):
        print(self.job_seeker_session)
        return super().get_context_data(**kwargs) | {
            "back_url": self.get_back_url(),
            "reset_url": self.get_reset_url(),
            "is_gps": self.is_gps,
            "page_title": "Créer un compte candidat",
            "can_view_personal_information": False,
        }


class CreateJobSeekerStepForSenderBaseView(CreateJobSeekerStepBaseView):
    def __init__(self):
        super().__init__()
        self.sender = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if self.sender.is_authenticated and self.sender.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            return HttpResponseRedirect(self.get_reset_url())
        return super().dispatch(request, *args, **kwargs)

    # def redirect_to_check_infos(self, job_seeker_public_id):
    #     return HttpResponseRedirect(
    #         reverse(
    #             "job_seekers_views:check_job_seeker_info",
    #             kwargs={"job_seeker_public_id": job_seeker_public_id},
    #         )
    #     )

    def redirect_to_check_email(self, session_uuid):
        return HttpResponseRedirect(
            reverse("job_seekers_views:search_by_email", kwargs={"session_uuid": session_uuid})
        )

    def redirect_to_apply_for(self, job_seeker):
        city_info = (
            f"&city={job_seeker.city_slug}" if self.request.user.can_view_personal_information(job_seeker) else ""
        )
        return HttpResponseRedirect(
            reverse("search:employers_results") + f"?job_seeker={job_seeker.public_id}" + city_info
        )


class CheckNIRForSenderView(CreateJobSeekerStepForSenderBaseView):
    # template_name = ""

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        session_nir = self.job_seeker_session.get("profile", {}).get("nir")
        self.form = CheckJobSeekerNirForm(job_seeker=None, data=request.POST or None, initial={"nir": session_nir})

    def post(self, request, *args, **kwargs):
        if self.form.data.get("skip"):
            # Redirect to search by e-mail address.
            self.job_seeker_session.update({"profile": {"nir": ""}})
            return self.redirect_to_check_email(self.job_seeker_session.name)

        context = {}
        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                self.job_seeker_session.update({"profile": {"nir": self.form.cleaned_data["nir"]}})
                return self.redirect_to_check_email(self.job_seeker_session.name)

            # The NIR we found is correct
            if self.form.data.get("confirm"):
                return self.redirect_to_apply_for(job_seeker)

            context = {
                # Ask the sender to confirm the NIR we found is associated to the correct user
                "preview_mode": bool(self.form.data.get("preview")),
                "job_seeker": job_seeker,
                "can_view_personal_information": self.request.user.can_view_personal_information(job_seeker),
            }

        return self.render_to_response(self.get_context_data(**kwargs) | context)

    def get_template_names(self):
        return [
            "job_seekers_views/step_check_job_seeker_nir_two_columns.html"
            if self.job_seeker_session.get("company")
            else "job_seekers_views/step_check_job_seeker_nir.html"
        ]

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "job_seeker": None,
            "preview_mode": False,
            "siae": self.company,
            "progress_title": "Étape 1/6 : Numéro de sécurité sociale du candidat",
            "progress": 20,
        }


class SearchByEmailForSenderView(CreateJobSeekerStepForSenderBaseView):
    template_name = "job_seekers_views/step_job_seeker_email.html"

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
                view_name = "job_seekers_views:create_job_seeker_step_1_for_sender"

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
                    pass
                else:
                    # if self.is_gps:
                    #     FollowUpGroup.objects.follow_beneficiary(
                    #         beneficiary=job_seeker, user=request.user, is_referent=True
                    #     )
                    #     return HttpResponseRedirect(reverse("gps:my_groups"))
                    # else:
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

    def get_template_names(self):
        return [
            "job_seekers_views/step_job_seeker_email_two_columns.html"
            if self.job_seeker_session.get("company")
            else "job_seekers_views/step_job_seeker_email.html"
        ]

    def get_back_url(self):
        return reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": self.job_seeker_session.name})

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "nir": self.job_seeker_session.get("profile", {}).get("nir"),
            "siae": self.company,
            "preview_mode": False,
            "progress_title": "Étape 2/6 : Adresse e-mail personnelle du candidat",
            "progress": 33,
        }


class CreateJobSeekerForSenderBaseView(CreateJobSeekerStepForSenderBaseView):
    def get_back_url(self):
        view_name = self.previous_url
        return reverse(
            view_name,
            kwargs={"session_uuid": self.job_seeker_session.name},
        ) + ("?gps=true" if self.is_gps else "")

    def get_next_url(self):
        view_name = self.next_url  # self.next_hire_url if self.hire_process else self.next_apply_url
        return reverse(
            view_name,
            kwargs={"session_uuid": self.job_seeker_session.name},
        ) + ("?gps=true" if self.is_gps else "")


class CreateJobSeekerStep1ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_1.html"
    required_session_namespaces = ["job_seeker_session"]

    previous_url = "job_seekers_views:search_by_email"
    next_url = "job_seekers_views:create_job_seeker_step_2_for_sender"

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

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "matomo_form_name": "apply-create-job-seeker-identity",
            "progress": "50",
            "progress_title": "Étape 3/6 : Quel est l'état civil du candidat ?",
        }


class CreateJobSeekerStep2ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_2.html"

    previous_url = "job_seekers_views:create_job_seeker_step_1_for_sender"
    next_url = "job_seekers_views:create_job_seeker_step_3_for_sender"

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
            "progress": "60",
            "progress_title": "Étape 4/6 : Quelles sont les coordonnées du candidat ?",
        }


class CreateJobSeekerStep3ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_3.html"

    previous_url = "job_seekers_views:create_job_seeker_step_2_for_sender"
    next_url = "job_seekers_views:create_job_seeker_step_end_for_sender"

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
            "progress": "75",
            "progress_title": "Étape 5/6 : Quelle est la situation du candidat",
        }


class CreateJobSeekerStepEndForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_end.html"

    previous_url = "job_seekers_views:create_job_seeker_step_3_for_sender"

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
        return self.job_seeker_session.get("end_url", reverse("dashboard:index"))

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                user = User.create_job_seeker_by_proxy(
                    self.sender, **self._get_user_data_from_session(), acting_organization=request.current_organization
                )
                self.profile = user.jobseeker_profile
                for k, v in self._get_profile_data_from_session().items():
                    setattr(self.profile, k, v)
                if request.user.is_employer:
                    self.profile.created_by_company = request.current_organization
                elif request.user.is_prescriber:
                    self.profile.created_by_prescriber_organization = request.current_organization
                self.profile.save()
                messages.success(
                    self.request,
                    (
                        f"Le compte du candidat {user.get_full_name()} a bien été "
                        "créé et ajouté à votre liste de candidats."
                    ),
                    extra_tags="toast",
                )
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

            url = self.get_next_url()
            self.job_seeker_session.delete()

            if self.is_gps:
                FollowUpGroup.objects.follow_beneficiary(beneficiary=user, user=request.user, is_referent=True)

        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        print(self.profile.__dict__)
        return super().get_context_data(**kwargs) | {
            "profile": self.profile,
            "progress": "80",
            "progress_title": "Étape 6/6 : Récapitulatif",
        }
