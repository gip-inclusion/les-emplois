import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.postgres.aggregates import ArrayAgg
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, DateTimeField, IntegerField, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, Concat, Lower
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_safe
from django.views.generic import DetailView, TemplateView, View

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis.exceptions import AddressLookupError
from itou.utils.auth import check_user
from itou.utils.emails import redact_email_address
from itou.utils.pagination import pager
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params, get_safe_url
from itou.www.apply.views.submit_views import ApplicationBaseView
from itou.www.gps import utils as gps_utils
from itou.www.job_seekers_views.enums import JobSeekerOrder, JobSeekerSessionKinds
from itou.www.job_seekers_views.forms import (
    CheckJobSeekerInfoForm,
    CheckJobSeekerNirForm,
    CreateOrUpdateJobSeekerStep1Form,
    CreateOrUpdateJobSeekerStep2Form,
    CreateOrUpdateJobSeekerStep3Form,
    FilterForm,
    JobSeekerExistsForm,
)


logger = logging.getLogger(__name__)


class JobSeekerDetailView(UserPassesTestMixin, DetailView):
    model = User
    queryset = User.objects.select_related("jobseeker_profile")
    slug_field = "public_id"
    slug_url_kwarg = "public_id"
    context_object_name = "job_seeker"

    def test_func(self):
        return self.request.user.is_prescriber or self.request.user.is_employer

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


@require_safe
@check_user(lambda user: user.is_prescriber)
def list_job_seekers(request, template_name="job_seekers_views/list.html", list_organization=False):
    if list_organization:
        if not request.current_organization or not request.current_organization.memberships.count() > 1:
            raise Http404
        job_seekers_ids = list(User.objects.linked_job_seeker_ids(request.user, request.current_organization))
    else:
        job_seekers_ids = list(User.objects.linked_job_seeker_ids(request.user, None))

    user_applications = JobApplication.objects.prescriptions_of(request.user, request.current_organization).filter(
        job_seeker=OuterRef("pk")
    )
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
    queryset = (
        User.objects.filter(kind=UserKind.JOB_SEEKER, pk__in=job_seekers_ids)
        .prefetch_related("approvals")
        .annotate(
            full_name=Concat(Lower("first_name"), Value(" "), Lower("last_name")),
            job_applications_nb=Coalesce(subquery_count, 0),
            last_updated_at=subquery_last_update,
            valid_eligibility_diagnosis=subquery_diagnosis,
            application_sent_by=ArrayAgg(
                "job_applications__sender", distinct=True, filter=Q(job_applications__sender__isnull=False)
            ),
        )
    )

    form = FilterForm(
        queryset,
        request.GET,
        request_user=request.user,
        request_organization=request.current_organization,
    )

    filters_counter = 0
    if form.is_valid():
        queryset = form.filter(queryset)
        filters_counter = form.get_filters_counter()

    try:
        order = JobSeekerOrder(request.GET.get("order"))
    except ValueError:
        order = JobSeekerOrder.FULL_NAME_ASC
    queryset = queryset.order_by(*order.order_by)

    page_obj = pager(queryset, request.GET.get("page"), items_per_page=10)
    for job_seeker in page_obj:
        job_seeker.user_can_view_personal_information = request.user.can_view_personal_information(job_seeker)

    context = {
        "back_url": get_safe_url(request, "back_url"),
        "list_organization": list_organization,
        "filters_form": form,
        "filters_counter": filters_counter,
        "order": order,
        "page_obj": page_obj,
        "mon_recap_banner_departments": settings.MON_RECAP_BANNER_DEPARTMENTS,
    }

    return render(request, "job_seekers_views/includes/list_results.html" if request.htmx else template_name, context)


class GetOrCreateJobSeekerStartView(View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.tunnel = request.GET.get("tunnel")
        if self.tunnel not in ("sender", "hire", "gps", "standalone"):
            raise Http404
        self.from_url = get_safe_url(request, "from_url")
        if not self.from_url:
            raise Http404

        company = None
        if self.tunnel == "sender" or self.tunnel == "hire":
            try:
                company = get_object_or_404(Company.objects.with_has_active_members(), pk=request.GET.get("company"))
            except ValueError:
                raise Http404("Aucune entreprise n'a été trouvée")

        data = {
            "config": {
                "tunnel": self.tunnel,
                "from_url": self.from_url,
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            }
        }
        data |= {"apply": {"company_pk": company.pk}} if company else {}
        self.job_seeker_session = SessionNamespace.create_uuid_namespace(request.session, data)

    def dispatch(self, request, *args, **kwargs):
        if request.user.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            raise PermissionDenied("Vous n'êtes pas autorisé à rechercher ou créer un compte candidat.")

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if self.tunnel in ("sender", "gps", "standalone"):
            view_name = "job_seekers_views:check_nir_for_sender"
        elif self.tunnel == "hire":
            view_name = "job_seekers_views:check_nir_for_hire"

        return HttpResponseRedirect(reverse(view_name, kwargs={"session_uuid": self.job_seeker_session.name}))


class ExpectedJobSeekerSessionMixin:
    EXPECTED_SESSION_KIND = None

    def __init__(self):
        self.job_seeker_session = None

    def setup(self, request, *args, session_uuid, **kwargs):
        self.job_seeker_session = SessionNamespace(request.session, session_uuid)
        if not self.job_seeker_session.exists():
            raise Http404
        # Ensure we are performing the action (update, create…) the session was created for.
        session_kind = self.job_seeker_session.get("config", {}).get("session_kind")
        if session_kind != self.EXPECTED_SESSION_KIND:
            raise Http404

        super().setup(request, *args, **kwargs)

    def get_reset_url(self):
        return self.job_seeker_session.get("config", {}).get("from_url") or reverse("dashboard:index")

    def get_back_url(self):
        return None

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "reset_url": self.get_reset_url(),
            "back_url": self.get_back_url(),
        }


class JobSeekerBaseView(ExpectedJobSeekerSessionMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.company = None
        self.hire_process = None
        self.prescription_proces = None
        self.auto_prescription_process = None
        self.standalone_creation = None
        self.is_gps = False

    def setup(self, request, *args, hire_process=False, **kwargs):
        super().setup(request, *args, **kwargs)
        self.is_gps = self.job_seeker_session.get("config", {}).get("tunnel") == "gps"
        if company_pk := self.job_seeker_session.get("apply", {}).get("company_pk"):
            if not self.is_gps:
                self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=company_pk)
        self.standalone_creation = not self.is_gps and self.company is None
        self.hire_process = hire_process
        self.prescription_process = (
            not self.hire_process
            and not self.is_gps
            and not self.standalone_creation
            and (
                request.user.is_prescriber
                or (request.user.is_employer and self.company != request.current_organization)
            )
        )
        self.auto_prescription_process = (
            not self.hire_process
            and not self.is_gps
            and not self.standalone_creation
            and request.user.is_employer
            and self.company == request.current_organization
        )

    def get_exit_url(self, job_seeker, created=False):
        if self.is_gps:
            return reverse("gps:group_list")
        if self.standalone_creation and self.is_job_seeker_in_user_jobseekers_list(job_seeker) and not created:
            params = {
                "job_seeker": job_seeker.public_id,
                "city": job_seeker.city_slug if self.request.user.can_view_personal_information(job_seeker) else "",
            }
            return add_url_params(reverse("search:employers_results"), params)
        if self.standalone_creation:
            return reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

        kwargs = {"company_pk": self.company.pk, "job_seeker_public_id": job_seeker.public_id}
        if created and self.hire_process:
            # The job seeker was just created, we don't need to check info if we are hiring
            if self.company.kind == CompanyKind.GEIQ:
                view_name = "apply:geiq_eligibility_for_hire"
            else:
                view_name = "apply:eligibility_for_hire"
        elif self.hire_process:
            # Hiring a job seeker that was found but not created: we check info
            view_name = "job_seekers_views:check_job_seeker_info_for_hire"
        elif created:
            # We created a job seeker, and we apply for them
            view_name = "apply:application_jobs"
        else:
            # We found a job seeker to apply for, so we check their info
            view_name = "job_seekers_views:check_job_seeker_info"
        return reverse(view_name, kwargs=kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "siae": self.company,
            "hire_process": self.hire_process,
            "prescription_process": self.prescription_process,
            "auto_prescription_process": self.auto_prescription_process,
            "standalone_creation": self.standalone_creation,
            "is_gps": self.is_gps,
        }

    def is_job_seeker_in_user_jobseekers_list(self, job_seeker):
        if not self.request.user.is_prescriber:
            return False

        return job_seeker.pk in User.objects.linked_job_seeker_ids(
            self.request.user, self.request.current_organization
        )


class JobSeekerForSenderBaseView(JobSeekerBaseView):
    def __init__(self):
        super().__init__()
        self.sender = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if self.sender.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)


class CheckNIRForJobSeekerView(JobSeekerBaseView):
    template_name = "job_seekers_views/step_check_job_seeker_nir.html"
    EXPECTED_SESSION_KIND = JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER

    def __init__(self):
        super().__init__()
        self.job_seeker = None
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.job_seeker = request.user
        self.form = CheckJobSeekerNirForm(job_seeker=self.job_seeker, data=request.POST or None)

    def dispatch(self, request, *args, **kwargs):
        if not self.job_seeker.is_job_seeker:
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # The NIR already exists, go to next step
        if self.job_seeker.jobseeker_profile.nir:
            # TODO(ewen): check_job_seeker_info doesn't use the session yet,
            # so we delete the session here.
            self.job_seeker_session.delete()
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
            # TODO(ewen): check_job_seeker_info doesn't use the session yet,
            # so we delete the session here.
            self.job_seeker_session.delete()
            return HttpResponseRedirect(
                reverse(
                    "job_seekers_views:check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
                )
            )
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


class CheckNIRForSenderView(JobSeekerForSenderBaseView):
    template_name = "job_seekers_views/step_check_job_seeker_nir.html"
    EXPECTED_SESSION_KIND = JobSeekerSessionKinds.GET_OR_CREATE

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
        return reverse(view_name, kwargs={"session_uuid": session_uuid})

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
                return HttpResponseRedirect(self.get_exit_url(job_seeker))

            context = {
                # Ask the sender to confirm the NIR we found is associated to the correct user
                "preview_mode": bool(self.form.data.get("preview")),
                "job_seeker": job_seeker,
                "can_view_personal_information": self.sender.can_view_personal_information(job_seeker),
                "is_job_seeker_in_list": self.is_job_seeker_in_user_jobseekers_list(job_seeker),
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


class SearchByEmailForSenderView(JobSeekerForSenderBaseView):
    template_name = "job_seekers_views/step_search_job_seeker_by_email.html"
    EXPECTED_SESSION_KIND = JobSeekerSessionKinds.GET_OR_CREATE

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
        is_job_seeker_in_list = False

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

                return HttpResponseRedirect(reverse(view_name, kwargs={"session_uuid": self.job_seeker_session.name}))

            # Ask the sender to confirm the email we found is associated to the correct user
            if self.form.data.get("preview"):
                preview_mode = True
                is_job_seeker_in_list = self.is_job_seeker_in_user_jobseekers_list(job_seeker)

            # The email we found is correct
            if self.form.data.get("confirm"):
                if not can_add_nir:
                    if self.is_gps:
                        gps_utils.add_beneficiary(request, job_seeker)
                    return HttpResponseRedirect(self.get_exit_url(job_seeker))

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
                        gps_utils.add_beneficiary(request, job_seeker)
                    return HttpResponseRedirect(self.get_exit_url(job_seeker))

        return self.render_to_response(
            self.get_context_data(**kwargs)
            | {
                "can_add_nir": can_add_nir,
                "preview_mode": preview_mode,
                "job_seeker": job_seeker,
                "can_view_personal_information": job_seeker and self.sender.can_view_personal_information(job_seeker),
                "is_job_seeker_in_list": is_job_seeker_in_list,
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
    EXPECTED_SESSION_KIND = JobSeekerSessionKinds.GET_OR_CREATE

    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def get_back_url(self):
        view_name = self.previous_hire_url if self.hire_process else self.previous_apply_url
        return reverse(
            view_name,
            kwargs={"session_uuid": self.job_seeker_session.name},
        )

    def get_next_url(self):
        view_name = self.next_hire_url if self.hire_process else self.next_apply_url
        return reverse(
            view_name,
            kwargs={"session_uuid": self.job_seeker_session.name},
        )

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
        session_birthdate = self.job_seeker_session.get("profile", {}).get("birthdate")
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
            "confirmation_needed": False,
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

        return {
            "birth_place_id": self.job_seeker_session.get("profile", {}).get("birth_place"),
            "birth_country_id": self.job_seeker_session.get("profile", {}).get("birth_country"),
        } | {k: v for k, v in self.job_seeker_session.get("profile").items() if k not in fields_to_exclude}

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.profile = JobSeekerProfile(
            user=User(**self._get_user_data_from_session()),
            **self._get_profile_data_from_session(),
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
                if request.user.is_prescriber:
                    self.profile.created_by_prescriber_organization = request.current_organization
                if self.standalone_creation:
                    messages.success(
                        request,
                        f"Le compte du candidat {self.profile.user.get_full_name()} a "
                        "bien été créé et ajouté à votre liste de candidats.",
                        extra_tags="toast",
                    )
                self.profile.save()
                # TODO(ewen): add tunnel information when we have it in self.tunnel
                logger.info("user=%s created job_seeker=%s", self.sender.pk, user.pk)
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
            url = self.get_exit_url(self.profile.user, created=True)

            if self.is_gps:
                notify_duplicate = (
                    User.objects.filter(kind=UserKind.JOB_SEEKER, first_name=user.first_name, last_name=user.last_name)
                    .exclude(pk=user.pk)
                    .exists()
                )
                gps_utils.add_beneficiary(request, user, notify_duplicate)

        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {"profile": self.profile, "progress": "80"}


class UpdateJobSeekerStartView(View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        try:
            job_seeker = get_object_or_404(
                User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=request.GET.get("job_seeker")
            )
        except ValidationError:
            raise Http404("Aucun candidat n'a été trouvé")

        from_url = get_safe_url(request, "from_url")
        if not from_url:
            raise Http404

        if request.user.is_job_seeker or not request.user.can_view_personal_information(job_seeker):
            raise PermissionDenied("Votre utilisateur n'est pas autorisé à vérifier les informations de ce candidat")

        self.job_seeker_session = SessionNamespace.create_uuid_namespace(
            request.session,
            data={
                "config": {"from_url": from_url, "session_kind": JobSeekerSessionKinds.UPDATE},
                "job_seeker_pk": job_seeker.pk,
            },
        )

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(
            reverse(
                "job_seekers_views:update_job_seeker_step_1", kwargs={"session_uuid": self.job_seeker_session.name}
            )
        )


class UpdateJobSeekerBaseView(ExpectedJobSeekerSessionMixin, TemplateView):
    EXPECTED_SESSION_KIND = JobSeekerSessionKinds.UPDATE

    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def get_job_seeker_queryset(self):
        return User.objects.filter(kind=UserKind.JOB_SEEKER)

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_seeker = get_object_or_404(
            self.get_job_seeker_queryset(), pk=self.job_seeker_session.get("job_seeker_pk")
        )
        if request.user.is_job_seeker or not request.user.can_view_personal_information(self.job_seeker):
            # Since the link leading to this process isn't visible to those users, this should never happen
            raise PermissionDenied("Votre utilisateur n'est pas autorisé à vérifier les informations de ce candidat")

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "update_job_seeker": True,
            "job_seeker": self.job_seeker,
            "step_3_url": reverse(
                "job_seekers_views:update_job_seeker_step_3",
                kwargs={"session_uuid": self.job_seeker_session.name},
            ),
            "reset_url": self.get_reset_url(),
            "readonly_form": False,
        }

    def _disable_form(self):
        for field in self.form:
            field.field.disabled = True

    def get_reset_url(self):
        return self.job_seeker_session.get("config").get("from_url")

    def get_back_url(self):
        return reverse(
            self.previous_url,
            kwargs={"session_uuid": self.job_seeker_session.name},
        )

    def get_next_url(self):
        return reverse(
            self.next_url,
            kwargs={"session_uuid": self.job_seeker_session.name},
        )


class UpdateJobSeekerStep1View(UpdateJobSeekerBaseView):
    template_name = "job_seekers_views/create_or_update_job_seeker/step_1.html"

    next_url = "job_seekers_views:update_job_seeker_step_2"

    def __init__(self):
        super().__init__()
        self.form = None

    def get_job_seeker_queryset(self):
        return super().get_job_seeker_queryset().select_related("jobseeker_profile")

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if not self.job_seeker_session.get("user"):
            self.job_seeker_session.set("user", {})
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

    def get_back_url(self):
        return self.get_reset_url()

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

    previous_url = "job_seekers_views:update_job_seeker_step_1"
    next_url = "job_seekers_views:update_job_seeker_step_3"

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

    previous_url = "job_seekers_views:update_job_seeker_step_2"
    next_url = "job_seekers_views:update_job_seeker_step_end"

    def __init__(self):
        super().__init__()
        self.form = None

    def get_job_seeker_queryset(self):
        return super().get_job_seeker_queryset().select_related("jobseeker_profile")

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = CreateOrUpdateJobSeekerStep3Form(
            instance=self.job_seeker.jobseeker_profile if self.job_seeker.has_jobseeker_profile else None,
            initial=self.job_seeker_session.get("profile", {}),
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

    previous_url = "job_seekers_views:update_job_seeker_step_3"

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
                kwargs={"session_uuid": self.job_seeker_session.name},
            )
        else:
            self.profile.save()
            url = self.get_exit_url()
            self.job_seeker_session.delete()
            logger.info("user=%s updated job_seeker=%s", request.user.pk, self.job_seeker.pk)
        return HttpResponseRedirect(url)

    def get_exit_url(self):
        return self.job_seeker_session.get("config").get("from_url")

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
