import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import storages
from django.db import transaction
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.generic import TemplateView

from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, JobDescription
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.files.models import File
from itou.job_applications.models import JobApplication
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis.exceptions import AddressLookupError
from itou.utils.emails import redact_email_address, send_email_messages
from itou.utils.session import SessionNamespace, SessionNamespaceRequiredMixin
from itou.www.apply.forms import (
    ApplicationJobsForm,
    CheckJobSeekerInfoForm,
    CheckJobSeekerNirForm,
    CreateOrUpdateJobSeekerStep1Form,
    CreateOrUpdateJobSeekerStep2Form,
    CreateOrUpdateJobSeekerStep3Form,
    SubmitJobApplicationForm,
    UserExistsForm,
)
from itou.www.apply.views import common as common_views, constants as apply_view_constants
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForm


logger = logging.getLogger(__name__)


JOB_SEEKER_INFOS_CHECK_PERIOD = relativedelta(months=6)


def _check_job_seeker_approval(request, job_seeker, siae):
    if job_seeker.approval_can_be_renewed_by(
        siae=siae, sender_prescriber_organization=request.current_organization if request.user.is_prescriber else None
    ):
        # NOTE(vperron): We're using PermissionDenied in order to display a message to the end user
        # by reusing the 403 template and its logic. I'm not 100% sure that this is a good idea but,
        # it's not too bad so far. I'd personnally would have raised a custom base error and caught it
        # somewhere using a middleware to display an error page that is not linked to a 403.
        if request.user == job_seeker:
            error = apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_USER
        else:
            error = apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        raise PermissionDenied(error)

    approval = job_seeker.latest_approval
    if approval and approval.is_valid():
        # Ensure that an existing approval can be unsuspended.
        if approval.is_suspended and not approval.can_be_unsuspended:
            error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_PROXY
            if request.user == job_seeker:
                error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_USER
            raise PermissionDenied(error)


class ApplyStepBaseView(LoginRequiredMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.company = None
        self.apply_session = None
        self.hire_process = None

    def setup(self, request, *args, **kwargs):
        self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=kwargs["company_pk"])
        self.apply_session = SessionNamespace(request.session, f"job_application-{self.company.pk}")
        self.hire_process = kwargs.pop("hire_process", False)
        super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if self.hire_process and request.user.kind != UserKind.EMPLOYER:
                raise PermissionDenied("Seuls les employeurs sont autorisés à déclarer des embauches")
            elif request.user.kind not in [
                UserKind.JOB_SEEKER,
                UserKind.PRESCRIBER,
                UserKind.EMPLOYER,
            ]:
                raise PermissionDenied("Vous n'êtes pas autorisé à déposer de candidature.")
            elif request.user.is_employer and not self.company.has_member(request.user):
                raise PermissionDenied("Vous ne pouvez postuler pour un candidat que dans votre structure.")

        if not self.company.has_active_members:
            raise PermissionDenied(
                "Cet employeur n'est pas inscrit, vous ne pouvez pas déposer de candidatures en ligne."
            )
        return super().dispatch(request, *args, **kwargs)

    def get_back_url(self):
        return None

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "siae": self.company,
            "back_url": self.get_back_url(),
            "hire_process": self.hire_process,
        }


class ApplicationBaseView(ApplyStepBaseView):
    def __init__(self):
        super().__init__()

        self.job_seeker = None
        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return
        self.job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=kwargs["job_seeker_pk"])
        _check_job_seeker_approval(request, self.job_seeker, self.company)
        if self.company.kind == CompanyKind.GEIQ:
            self.geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.job_seeker, self.company
            ).first()
        else:
            # General IAE eligibility case
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, for_siae=self.company
            )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
            "eligibility_diagnosis": self.eligibility_diagnosis,
            "is_subject_to_eligibility_rules": self.company.is_subject_to_eligibility_rules,
            "geiq_eligibility_diagnosis": self.geiq_eligibility_diagnosis,
            "is_subject_to_geiq_eligibility_rules": self.company.kind == CompanyKind.GEIQ,
            "can_edit_personal_information": self.request.user.can_edit_personal_information(self.job_seeker),
            "can_view_personal_information": self.request.user.can_view_personal_information(self.job_seeker),
            # Do not show the warning for job seekers
            "new_check_needed": (
                not self.request.user.is_job_seeker
                and self.job_seeker.last_checked_at < timezone.now() - JOB_SEEKER_INFOS_CHECK_PERIOD
            ),
        }

    def get_previous_applications_queryset(self):
        # Useful in CheckPreviousApplications and ApplicationJobsView
        return self.job_seeker.job_applications.filter(to_company=self.company)


class ApplyStepForSenderBaseView(ApplyStepBaseView):
    def __init__(self):
        super().__init__()
        self.sender = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if self.sender.is_authenticated and self.sender.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            return HttpResponseRedirect(reverse("apply:start", kwargs={"company_pk": self.company.pk}))
        return super().dispatch(request, *args, **kwargs)

    def redirect_to_check_infos(self, job_seeker_pk):
        view_name = "apply:check_job_seeker_info_for_hire" if self.hire_process else "apply:step_check_job_seeker_info"
        return HttpResponseRedirect(
            reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": job_seeker_pk})
        )


class StartView(ApplyStepBaseView):
    def get(self, request, *args, **kwargs):
        # SIAE members can only submit a job application to their SIAE
        if request.user.is_employer:
            if suspension_explanation := self.company.get_active_suspension_text_with_dates():
                raise PermissionDenied(
                    "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle "
                    "a posteriori. " + suspension_explanation
                )

        # Refuse all applications except those made by an SIAE member
        if self.company.block_job_applications and not self.company.has_member(request.user):
            raise Http404("Cette organisation n'accepte plus de candidatures pour le moment.")

        # Create a sub-session for this job application process
        self.apply_session.init(
            {
                "selected_jobs": [request.GET["job_description_id"]] if "job_description_id" in request.GET else [],
            }
        )
        # Warn message if prescriber's authorization is pending
        if (
            request.user.is_prescriber
            and request.current_organization
            and request.current_organization.has_pending_authorization()
        ):
            return HttpResponseRedirect(
                reverse("apply:pending_authorization_for_sender", kwargs={"company_pk": self.company.pk})
            )

        tunnel = "job_seeker" if request.user.is_job_seeker else "sender"
        return HttpResponseRedirect(reverse(f"apply:check_nir_for_{tunnel}", kwargs={"company_pk": self.company.pk}))


class PendingAuthorizationForSender(ApplyStepForSenderBaseView):
    template_name = "apply/submit_step_pending_authorization.html"


class CheckNIRForJobSeekerView(ApplyStepBaseView):
    template_name = "apply/submit_step_check_job_seeker_nir.html"

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
        if self.job_seeker.nir:
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.data.get("skip"):
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        if self.form.is_valid():
            self.job_seeker.nir = self.form.cleaned_data["nir"]
            self.job_seeker.lack_of_nir_reason = ""
            self.job_seeker.save()
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
        }


class CheckNIRForSenderView(ApplyStepForSenderBaseView):
    template_name = "apply/submit_step_check_job_seeker_nir.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CheckJobSeekerNirForm(job_seeker=None, data=request.POST or None)

    def redirect_to_check_email(self, session_uuid):
        view_name = "apply:search_by_email_for_hire" if self.hire_process else "apply:search_by_email_for_sender"
        return HttpResponseRedirect(
            reverse(view_name, kwargs={"company_pk": self.company.pk, "session_uuid": session_uuid})
        )

    def post(self, request, *args, **kwargs):
        if self.form.data.get("skip"):
            # Redirect to search by e-mail address.
            job_seeker_session = SessionNamespace.create_temporary(request.session)
            job_seeker_session.init({"user": {"nir": ""}})
            return self.redirect_to_check_email(job_seeker_session.name)

        context = {}
        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                job_seeker_session = SessionNamespace.create_temporary(request.session)
                job_seeker_session.init({"user": {"nir": self.form.cleaned_data["nir"]}})
                return self.redirect_to_check_email(job_seeker_session.name)

            # The NIR we found is correct
            if self.form.data.get("confirm"):
                return self.redirect_to_check_infos(job_seeker.pk)

            context = {
                # Ask the sender to confirm the NIR we found is associated to the correct user
                "preview_mode": bool(self.form.data.get("preview")),
                "job_seeker": job_seeker,
                "can_view_personal_information": self.sender.can_view_personal_information(job_seeker),
            }

        return self.render_to_response(self.get_context_data(**kwargs) | context)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
        }


class SearchByEmailForSenderView(SessionNamespaceRequiredMixin, ApplyStepForSenderBaseView):
    required_session_namespaces = ["job_seeker_session"]
    template_name = "apply/submit_step_job_seeker.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        self.job_seeker_session = SessionNamespace(request.session, kwargs["session_uuid"])
        super().setup(request, *args, **kwargs)
        self.form = UserExistsForm(initial=self.job_seeker_session.get("user", {}), data=request.POST or None)

    def post(self, request, *args, **kwargs):
        can_add_nir = False
        preview_mode = False
        job_seeker = None

        if self.form.is_valid():
            job_seeker = self.form.get_user()
            nir = self.job_seeker_session.get("user", {}).get("nir", "")
            can_add_nir = nir and self.sender.can_add_nir(job_seeker)

            # No user found with that email, redirect to create a new account.
            if not job_seeker:
                user_infos = self.job_seeker_session.get("user", {})
                user_infos.update({"email": self.form.cleaned_data["email"], "nir": nir})
                self.job_seeker_session.update({"user": user_infos})
                view_name = (
                    "apply:create_job_seeker_step_1_for_hire"
                    if self.hire_process
                    else "apply:create_job_seeker_step_1_for_sender"
                )

                return HttpResponseRedirect(
                    reverse(
                        view_name, kwargs={"company_pk": self.company.pk, "session_uuid": self.job_seeker_session.name}
                    )
                )

            # Ask the sender to confirm the email we found is associated to the correct user
            if self.form.data.get("preview"):
                preview_mode = True

            # The email we found is correct
            if self.form.data.get("confirm"):
                if not can_add_nir:
                    return self.redirect_to_check_infos(job_seeker.pk)

                try:
                    job_seeker.nir = nir
                    job_seeker.lack_of_nir_reason = ""
                    job_seeker.save(update_fields=["nir", "lack_of_nir_reason"])
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
                    return self.redirect_to_check_infos(job_seeker.pk)

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
        view_name = "apply:check_nir_for_hire" if self.hire_process else "apply:check_nir_for_sender"
        return reverse(view_name, kwargs={"company_pk": self.company.pk})

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "nir": self.job_seeker_session.get("user", {}).get("nir"),
            "siae": self.company,
        }


class CreateJobSeekerForSenderBaseView(SessionNamespaceRequiredMixin, ApplyStepForSenderBaseView):
    required_session_namespaces = ["job_seeker_session"]

    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def setup(self, request, *args, **kwargs):
        self.job_seeker_session = SessionNamespace(request.session, kwargs["session_uuid"])
        super().setup(request, *args, **kwargs)

    def get_back_url(self):
        view_name = self.previous_hire_url if self.hire_process else self.previous_apply_url
        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "session_uuid": self.job_seeker_session.name},
        )

    def get_next_url(self):
        view_name = self.next_hire_url if self.hire_process else self.next_apply_url
        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "session_uuid": self.job_seeker_session.name},
        )


class CreateJobSeekerStep1ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_1.html"

    previous_apply_url = "apply:search_by_email_for_sender"
    previous_hire_url = "apply:search_by_email_for_hire"
    next_apply_url = "apply:create_job_seeker_step_2_for_sender"
    next_hire_url = "apply:create_job_seeker_step_2_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CreateOrUpdateJobSeekerStep1Form(
            data=request.POST or None, initial=self.job_seeker_session.get("user", {})
        )

    def post(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        context["confirmation_needed"] = False
        if self.form.is_valid():
            existing_job_seeker = User.objects.filter(
                kind=UserKind.JOB_SEEKER,
                birthdate=self.form.cleaned_data["birthdate"],
                first_name__unaccent__iexact=self.form.cleaned_data["first_name"],
                last_name__unaccent__iexact=self.form.cleaned_data["last_name"],
            ).first()
            if existing_job_seeker and not self.form.data.get("confirm"):
                # If an existing job seeker matches the info, a confirmation is required
                context["confirmation_needed"] = True
                context["redacted_existing_email"] = redact_email_address(existing_job_seeker.email)
                context["email_to_create"] = self.job_seeker_session.get("user", {}).get("email", "")

            if not context["confirmation_needed"]:
                self.job_seeker_session.set("user", self.job_seeker_session.get("user", {}) | self.form.cleaned_data)
                return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "20",
        }


class CreateJobSeekerStep2ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_2.html"

    previous_apply_url = "apply:create_job_seeker_step_1_for_sender"
    previous_hire_url = "apply:create_job_seeker_step_1_for_hire"
    next_apply_url = "apply:create_job_seeker_step_3_for_sender"
    next_hire_url = "apply:create_job_seeker_step_3_for_hire"

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
    template_name = "apply/submit/create_or_update_job_seeker/step_3.html"

    previous_apply_url = "apply:create_job_seeker_step_2_for_sender"
    previous_hire_url = "apply:create_job_seeker_step_2_for_hire"
    next_apply_url = "apply:create_job_seeker_step_end_for_sender"
    next_hire_url = "apply:create_job_seeker_step_end_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = CreateOrUpdateJobSeekerStep3Form(
            data=request.POST or None,
            initial=self.job_seeker_session.get("profile", {})
            | {
                "pole_emploi_id": self.job_seeker_session.get("user").get("pole_emploi_id"),
                "lack_of_pole_emploi_id_reason": self.job_seeker_session.get("user").get(
                    "lack_of_pole_emploi_id_reason"
                ),
            },
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker_session.set(
                "profile",
                {
                    k: v
                    for k, v in self.form.cleaned_data.items()
                    if k not in ["pole_emploi_id", "lack_of_pole_emploi_id_reason"]
                },
            )
            self.job_seeker_session.set(
                "user",
                self.job_seeker_session.get("user")
                | {
                    "pole_emploi_id": self.form.cleaned_data.get("pole_emploi_id"),
                    "lack_of_pole_emploi_id_reason": self.form.cleaned_data.get("lack_of_pole_emploi_id_reason"),
                },
            )
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "60",
        }


class CreateJobSeekerStepEndForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_end.html"

    previous_apply_url = "apply:create_job_seeker_step_3_for_sender"
    previous_hire_url = "apply:create_job_seeker_step_3_for_hire"
    next_apply_url = "apply:application_jobs"
    next_hire_url = None  # Depends on GEIQ/non-GEIQ

    def __init__(self):
        super().__init__()
        self.profile = None

    def _get_user_data_from_session(self):
        return {k: v for k, v in self.job_seeker_session.get("user").items() if k not in ["city_slug", "lack_of_nir"]}

    def _get_profile_data_from_session(self):
        # Dummy fields used by CreateOrUpdateJobSeekerStep3Form()
        fields_to_exclude = [
            "pole_emploi",
            "pole_emploi_id_forgotten",
            "rsa_allocation",
            "unemployed",
            "ass_allocation",
            "aah_allocation",
        ]
        return {k: v for k, v in self.job_seeker_session.get("profile").items() if k not in fields_to_exclude}

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.profile = JobSeekerProfile(
            user=User(**self._get_user_data_from_session()),
            **self._get_profile_data_from_session(),
        )

    def get_next_url(self):
        if self.hire_process:
            if self.company.kind == CompanyKind.GEIQ:
                view_name = "apply:geiq_eligibility_for_hire"
            else:
                view_name = "apply:eligibility_for_hire"
        else:
            view_name = self.next_apply_url

        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.profile.user.pk},
        )

    def post(self, request, *args, **kwargs):
        try:
            user = User.create_job_seeker_by_proxy(self.sender, **self._get_user_data_from_session())
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            url = reverse("dashboard:index")
        else:
            self.profile = user.jobseeker_profile
            for k, v in self._get_profile_data_from_session().items():
                setattr(self.profile, k, v)
            self.profile.save()

            try:
                user.set_coords(user.address_line_1, user.post_code)
            except AddressLookupError:
                # Nothing to do: re-raised and already logged as error
                pass
            else:
                user.save()

            self.job_seeker_session.delete()
            url = self.get_next_url()
        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.profile,
            "progress": "80",
        }


class CheckJobSeekerInformations(ApplicationBaseView):
    """
    Ensure the job seeker has all required info.
    """

    template_name = "apply/submit_step_job_seeker_check_info.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = CheckJobSeekerInfoForm(instance=self.job_seeker, data=request.POST or None)

    def get(self, request, *args, **kwargs):
        # Check required info that will allow us to find a pre-existing approval.
        has_required_info = self.job_seeker.birthdate and (
            self.job_seeker.pole_emploi_id or self.job_seeker.lack_of_pole_emploi_id_reason
        )
        if has_required_info:
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_prev_applications",
                    kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.form.save()
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_prev_applications",
                    kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
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

    template_name = "apply/submit/check_job_seeker_info_for_hire.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        assert self.hire_process

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.job_seeker.jobseeker_profile,
            "hiring_pending": True,
        }


class CheckPreviousApplications(ApplicationBaseView):
    """
    Check previous job applications to avoid duplicates.
    """

    template_name = "apply/submit_step_check_prev_applications.html"

    def __init__(self):
        super().__init__()

        self.previous_applications = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            # Otherwise LoginRequiredMixin will raise in dispatch()
            self.previous_applications = self.get_previous_applications_queryset()

    def get_next_url(self):
        if self.hire_process:
            view_name = (
                "apply:geiq_eligibility_for_hire"
                if self.company.kind == CompanyKind.GEIQ
                else "apply:eligibility_for_hire"
            )
        else:
            view_name = "apply:application_jobs"
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk})

    def get(self, request, *args, **kwargs):
        if not self.previous_applications.exists():
            return HttpResponseRedirect(self.get_next_url())

        # Limit the possibility of applying to the same SIAE for 24 hours.
        if not request.user.is_employer and self.previous_applications.created_in_past(hours=24).exists():
            if request.user == self.job_seeker:
                msg = "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures."
            else:
                msg = "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures."
            raise PermissionDenied(msg)

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        # At this point we know that the candidate is applying to an SIAE where he or she has already applied.
        # Allow a new job application if the user confirm it despite the duplication warning.
        if request.POST.get("force_new_application") == "force":
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "prev_application": self.previous_applications.latest("created_at"),
        }


class ApplicationJobsView(ApplicationBaseView):
    template_name = "apply/submit/application/jobs.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if not self.apply_session.exists():
            self.apply_session.init({})

        self.form = ApplicationJobsForm(
            self.company,
            initial={"selected_jobs": self.apply_session.get("selected_jobs", [])},
            data=request.POST or None,
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.apply_session.set("selected_jobs", self.form.cleaned_data.get("selected_jobs", []))
            # dispatching to IAE or GEIQ eligibility
            path_name = (
                "application_geiq_eligibility" if self.company.kind == CompanyKind.GEIQ else "application_eligibility"
            )
            return HttpResponseRedirect(
                reverse(
                    "apply:" + path_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk}
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        job_descriptions_by_pk = {jd.pk: jd for jd in self.form.fields["selected_jobs"].queryset}
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "job_descriptions_by_pk": job_descriptions_by_pk,
            "progress": 25,
            "full_content_width": bool(job_descriptions_by_pk),
        }

    def get_back_url(self):
        if self.get_previous_applications_queryset().exists():
            return reverse(
                "apply:step_check_prev_applications",
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
            )

        return reverse(
            "apply:step_check_job_seeker_info",
            kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
        )


class ApplicationEligibilityView(ApplicationBaseView):
    template_name = "apply/submit/application/eligibility.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        initial_data = {}

        if self.eligibility_diagnosis:
            initial_data["administrative_criteria"] = self.eligibility_diagnosis.administrative_criteria.all()

        self.form = AdministrativeCriteriaForm(
            request.user,
            siae=self.company,
            initial=initial_data,
            data=request.POST or None,
        )

    def get_next_url(self):
        return reverse(
            "apply:application_resume", kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk}
        )

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            # Otherwise LoginRequiredMixin will raise in dispatch()
            bypass_eligibility_conditions = [
                # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
                not self.company.is_subject_to_eligibility_rules,
                # Only "authorized prescribers" can perform an eligibility diagnosis.
                not (
                    request.user.is_prescriber
                    and request.current_organization
                    and request.current_organization.is_authorized
                ),
                # No need for eligibility diagnosis if the job seeker already have a PASS IAE
                self.job_seeker.has_valid_common_approval,
            ]
            if any(bypass_eligibility_conditions):
                return HttpResponseRedirect(self.get_next_url())

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            if not self.eligibility_diagnosis:
                EligibilityDiagnosis.create_diagnosis(
                    self.job_seeker,
                    author=request.user,
                    author_organization=request.current_organization,
                    administrative_criteria=self.form.cleaned_data,
                )
            elif self.eligibility_diagnosis and not self.form.data.get("shrouded"):
                EligibilityDiagnosis.update_diagnosis(
                    self.eligibility_diagnosis,
                    author=request.user,
                    author_organization=request.current_organization,
                    administrative_criteria=self.form.cleaned_data,
                )
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        new_expires_at_if_updated = timezone.now() + relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS)

        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "new_expires_at_if_updated": new_expires_at_if_updated,
            "progress": 50,
            "job_seeker": self.job_seeker,
            "back_url": reverse(
                "apply:application_jobs", kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk}
            ),
            "full_content_width": True,
        }


class ApplicationGEIQEligibilityView(ApplicationBaseView):
    template_name = "apply/submit/application/geiq_eligibility.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return

        self.form = GEIQAdministrativeCriteriaForm(
            company=self.company,
            administrative_criteria=(
                self.geiq_eligibility_diagnosis.administrative_criteria.all()
                if self.geiq_eligibility_diagnosis
                else []
            ),
            form_url=reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
            data=request.POST or None,
        )

    def get_next_url(self):
        return reverse(
            "apply:application_resume", kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk}
        )

    def dispatch(self, request, *args, **kwargs):
        # GEIQ eligibility form during job application process is only available to authorized prescribers
        if request.user.is_authenticated and not request.user.is_prescriber_with_authorized_org:
            return HttpResponseRedirect(self.get_next_url())

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        geo_criteria_detected = self.job_seeker.address_in_qpv or self.job_seeker.zrr_city_name
        return super().get_context_data(**kwargs) | {
            "back_url": reverse(
                "apply:application_jobs", kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk}
            ),
            "form": self.form,
            "full_content_width": True,
            "geo_criteria_detected": geo_criteria_detected,
            "progress": 50,
        }

    def post(self, request, *args, **kwargs):
        if request.htmx:
            return render(
                request, "apply/includes/geiq/geiq_administrative_criteria_form.html", self.get_context_data(**kwargs)
            )
        elif self.form.is_valid():
            if not self.geiq_eligibility_diagnosis:
                GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
                    self.job_seeker,
                    request.user,
                    request.current_organization if request.user.is_prescriber else None,
                    self.form.cleaned_data,
                )
            else:
                # Check if update is really needed: may change diagnosis expiration date
                if self.form.has_changed():
                    GEIQEligibilityDiagnosis.update_eligibility_diagnosis(
                        self.geiq_eligibility_diagnosis, request.user, self.form.cleaned_data
                    )

            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))


class ApplicationResumeView(ApplicationBaseView):
    template_name = "apply/submit/application/resume.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return

        if not self.apply_session.exists():
            self.apply_session.init({})

        self.form = SubmitJobApplicationForm(
            company=self.company,
            user=request.user,
            initial={"selected_jobs": self.apply_session.get("selected_jobs", [])},
            data=request.POST or None,
            files=request.FILES or None,
        )

    def post(self, request, *args, **kwargs):
        # Prevent multiple rapid clicks on the submit button to create multiple job applications.
        job_application = (
            self.job_seeker.job_applications.filter(to_company=self.company).created_in_past(seconds=10).first()
        )
        if job_application:
            return HttpResponseRedirect(
                reverse(
                    "apply:application_end",
                    kwargs={"company_pk": self.company.pk, "application_pk": job_application.pk},
                )
            )
        if self.form.is_valid():
            # Fill the job application with the required information
            job_application = JobApplication(
                job_seeker=self.job_seeker,
                to_company=self.company,
                sender=request.user,
                sender_kind=request.user.kind,
                message=self.form.cleaned_data["message"],
            )
            if request.user.is_prescriber:
                job_application.sender_prescriber_organization = request.current_organization
            if request.user.is_employer:
                job_application.sender_company = request.current_organization

            if resume := self.form.cleaned_data.get("resume"):
                key = f"resume/{uuid.uuid4()}.pdf"
                File.objects.create(key=key)
                public_storage = storages["public"]
                name = public_storage.save(key, resume)
                job_application.resume_link = public_storage.url(name)

            # Save the job application
            with transaction.atomic():
                job_application.save()
                job_application.selected_jobs.add(*self.form.cleaned_data["selected_jobs"])
            # The job application is now saved in DB, delete the session early to avoid any problems
            self.apply_session.delete()

            try:
                # Send email notifications
                if job_application.is_spontaneous:
                    notification = NewSpontaneousJobAppEmployersNotification(job_application=job_application)
                else:
                    notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)

                notification.send()

                job_application_emails = [job_application.email_new_for_job_seeker()]

                if request.user.is_prescriber:
                    job_application_emails.append(job_application.email_new_for_prescriber)

                send_email_messages(job_application_emails)

            finally:
                # We are done, send to the (mostly) stateless final page as we now have no session.
                # "company_pk" is kinda useless with "application_pk" but is kept for URL consistency.
                return HttpResponseRedirect(
                    reverse(
                        "apply:application_end",
                        kwargs={"company_pk": self.company.pk, "application_pk": job_application.pk},
                    )
                )
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_back_url(self):
        view_name = "apply:application_jobs"
        if self.company.kind == CompanyKind.GEIQ and self.request.user.is_prescriber_with_authorized_org:
            view_name = "apply:application_geiq_eligibility"
        elif self.company.kind != CompanyKind.GEIQ:
            bypass_eligibility_conditions = [
                # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
                not self.company.is_subject_to_eligibility_rules,
                # Only "authorized prescribers" can perform an eligibility diagnosis.
                not (
                    self.request.user.is_prescriber
                    and self.request.current_organization
                    and self.request.current_organization.is_authorized
                ),
                # No need for eligibility diagnosis if the job seeker already have a PASS IAE
                self.job_seeker.has_valid_common_approval,
            ]
            if not any(bypass_eligibility_conditions):
                view_name = "apply:application_eligibility"

        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "resume_is_recommended": any(
                JobDescription.objects.filter(pk__in=self.apply_session.get("selected_jobs", [])).values_list(
                    "is_resume_mandatory", flat=True
                )
            ),
            "progress": 75,
            "full_content_width": True,
        }


class ApplicationEndView(ApplyStepBaseView):
    template_name = "apply/submit/application/end.html"

    def __init__(self):
        super().__init__()

        self.job_application = None
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_application = get_object_or_404(
            JobApplication.objects.select_related("job_seeker", "to_company"),
            pk=kwargs.get("application_pk"),
        )
        self.form = CreateOrUpdateJobSeekerStep2Form(
            instance=self.job_application.job_seeker, data=request.POST or None
        )

    def post(self, request, *args, **kwargs):
        if not self.request.user.can_edit_personal_information(self.job_application.job_seeker):
            raise PermissionDenied("Votre utilisateur n'est pas autorisé à modifier les informations de ce candidat")
        if self.form.is_valid():
            self.form.save()
            # Redirect to the same page, so we don't have a POST method
            return HttpResponseRedirect(request.path_info)
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_application": self.job_application,
            "form": self.form,
            "can_edit_personal_information": self.request.user.can_edit_personal_information(
                self.job_application.job_seeker
            ),
            "can_view_personal_information": self.request.user.can_view_personal_information(
                self.job_application.job_seeker
            ),
        }


class UpdateJobSeekerBaseView(SessionNamespaceRequiredMixin, ApplyStepBaseView):
    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def setup(self, request, *args, **kwargs):
        self.job_seeker = get_object_or_404(User, pk=kwargs["job_seeker_pk"])
        self.job_seeker_session = SessionNamespace(request.session, f"job_seeker-{self.job_seeker.pk}")
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
                "apply:update_job_seeker_step_3_for_hire" if self.hire_process else "apply:update_job_seeker_step_3",
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
        }

    def _disable_form(self):
        for field in self.form:
            field.field.disabled = True

    def get_back_url(self):
        view_name = self.previous_hire_url if self.hire_process else self.previous_apply_url
        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
        )

    def get_next_url(self):
        view_name = self.next_hire_url if self.hire_process else self.next_apply_url
        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
        )


class UpdateJobSeekerStep1View(UpdateJobSeekerBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_1.html"

    previous_apply_url = "apply:application_jobs"
    previous_hire_url = "apply:check_job_seeker_info_for_hire"
    next_apply_url = "apply:update_job_seeker_step_2"
    next_hire_url = "apply:update_job_seeker_step_2_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return
        if not self.job_seeker_session.exists():
            self.job_seeker_session.init({"user": {}})

        self.form = CreateOrUpdateJobSeekerStep1Form(
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
            self.job_seeker_session.set("user", self.job_seeker_session.get("user", {}) | self.form.cleaned_data)
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "readonly_form": not self.request.user.can_edit_personal_information(self.job_seeker),
            "progress": "20",
        }


class UpdateJobSeekerStep2View(UpdateJobSeekerBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_2.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

    previous_apply_url = "apply:update_job_seeker_step_1"
    previous_hire_url = "apply:update_job_seeker_step_1_for_hire"
    next_apply_url = "apply:update_job_seeker_step_3"
    next_hire_url = "apply:update_job_seeker_step_3_for_hire"

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
    template_name = "apply/submit/create_or_update_job_seeker/step_3.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

    previous_apply_url = "apply:update_job_seeker_step_2"
    previous_hire_url = "apply:update_job_seeker_step_2_for_hire"
    next_apply_url = "apply:update_job_seeker_step_end"
    next_hire_url = "apply:update_job_seeker_step_end_for_hire"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        session_pole_emploi_id = self.job_seeker_session.get("user").get("pole_emploi_id")
        session_lack_of_pole_emploi_id_reason = self.job_seeker_session.get("user").get(
            "lack_of_pole_emploi_id_reason"
        )
        initial_form_data = self.job_seeker_session.get("profile", {}) | {
            "pole_emploi_id": session_pole_emploi_id
            if session_pole_emploi_id is not None
            else self.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": session_lack_of_pole_emploi_id_reason
            if session_lack_of_pole_emploi_id_reason is not None
            else self.job_seeker.lack_of_pole_emploi_id_reason,
        }
        self.form = CreateOrUpdateJobSeekerStep3Form(
            instance=self.job_seeker.jobseeker_profile if self.job_seeker.has_jobseeker_profile else None,
            initial=initial_form_data,
            data=request.POST or None,
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker_session.set(
                "profile",
                {
                    k: v
                    for k, v in self.form.cleaned_data.items()
                    if k not in ["pole_emploi_id", "lack_of_pole_emploi_id_reason"]
                },
            )
            self.job_seeker_session.set(
                "user",
                self.job_seeker_session.get("user")
                | {
                    "pole_emploi_id": self.form.cleaned_data.get("pole_emploi_id"),
                    "lack_of_pole_emploi_id_reason": self.form.cleaned_data.get("lack_of_pole_emploi_id_reason"),
                },
            )
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "60",
        }


class UpdateJobSeekerStepEndView(UpdateJobSeekerBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_end.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

    previous_apply_url = "apply:update_job_seeker_step_3"
    previous_hire_url = "apply:update_job_seeker_step_3_for_hire"
    next_apply_url = "apply:application_jobs"
    next_hire_url = "apply:check_job_seeker_info_for_hire"

    def __init__(self):
        super().__init__()
        self.profile = None
        self.updated_user_fields = []

    def _get_profile_data_from_session(self):
        # Dummy fields used by CreateOrUpdateJobSeekerStep3Form()
        fields_to_exclude = [
            "pole_emploi",
            "pole_emploi_id_forgotten",
            "rsa_allocation",
            "unemployed",
            "ass_allocation",
            "aah_allocation",
        ]
        return {k: v for k, v in self.job_seeker_session.get("profile", {}).items() if k not in fields_to_exclude}

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        allowed_user_fields_to_update = ["pole_emploi_id", "lack_of_pole_emploi_id_reason"]
        if self.request.user.can_edit_personal_information(self.job_seeker):
            allowed_user_fields_to_update.extend(CreateOrUpdateJobSeekerStep1Form.Meta.fields)
            allowed_user_fields_to_update.extend(CreateOrUpdateJobSeekerStep2Form.Meta.fields)
            allowed_user_fields_to_update.remove("city_slug")

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
                    self.job_seeker.set_coords(self.job_seeker.address_line_1, self.job_seeker.post_code)
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
                "apply:update_job_seeker_step_1",
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
            )
        else:
            self.profile.save()
            self.job_seeker_session.delete()
            url = self.get_next_url()
        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.profile,
            "progress": "80",
        }


@login_required
def eligibility_for_hire(request, company_pk, job_seeker_pk, template_name="apply/submit/eligibility_for_hire.html"):
    company = get_object_or_404(Company.objects.member_required(request.user), pk=company_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    _check_job_seeker_approval(request, job_seeker, company)
    next_url = reverse("apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
    bypass_eligibility_conditions = [
        # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
        not company.is_subject_to_eligibility_rules,
        # No need for eligibility diagnosis if the job seeker already has a PASS IAE
        job_seeker.has_valid_common_approval,
    ]
    if any(bypass_eligibility_conditions) or job_seeker.has_valid_diagnosis(for_siae=company):
        return HttpResponseRedirect(next_url)
    return common_views._eligibility(
        request,
        company,
        job_seeker,
        cancel_url=reverse(
            "apply:check_job_seeker_info_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        ),
        next_url=next_url,
        template_name=template_name,
        extra_context={"hire_process": True},
    )


@login_required
def geiq_eligibility_for_hire(
    request, company_pk, job_seeker_pk, template_name="apply/submit/geiq_eligibility_for_hire.html"
):
    company = get_object_or_404(
        Company.objects.member_required(request.user).filter(kind=CompanyKind.GEIQ), pk=company_pk
    )
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    next_url = reverse("apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
    if GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, company).exists():
        return HttpResponseRedirect(next_url)
    return common_views._geiq_eligibility(
        request,
        company,
        job_seeker,
        back_url=reverse(
            "apply:check_job_seeker_info_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        ),
        next_url=next_url,
        geiq_eligibility_criteria_url=reverse(
            "apply:geiq_eligibility_criteria_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
        ),
        template_name=template_name,
        extra_context={"hire_process": True},
    )


@login_required
def geiq_eligibility_criteria_for_hire(request, company_pk, job_seeker_pk):
    company = get_object_or_404(
        Company.objects.member_required(request.user).filter(kind=CompanyKind.GEIQ), pk=company_pk
    )
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    return common_views._geiq_eligibility_criteria(
        request,
        company,
        job_seeker,
    )


@login_required
def hire_confirmation(request, company_pk, job_seeker_pk, template_name="apply/submit/hire_confirmation.html"):
    company = get_object_or_404(Company.objects.member_required(request.user), pk=company_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    if company.kind == CompanyKind.GEIQ:
        geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, company).first()
        eligibility_diagnosis = None
    else:
        _check_job_seeker_approval(request, job_seeker, company)
        # General IAE eligibility case
        eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(job_seeker, for_siae=company)
        geiq_eligibility_diagnosis = None
    return common_views._accept(
        request,
        company,
        job_seeker,
        error_url=reverse(
            "apply:hire_confirmation", kwargs={"company_pk": company_pk, "job_seeker_pk": job_seeker_pk}
        ),
        back_url=reverse(
            "apply:check_job_seeker_info_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        ),
        template_name=template_name,
        extra_context={
            "can_edit_personal_information": request.user.can_edit_personal_information(job_seeker),
            "is_subject_to_eligibility_rules": company.is_subject_to_eligibility_rules,
            "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
            "eligibility_diagnosis": eligibility_diagnosis,
            "is_subject_to_geiq_eligibility_rules": company.kind == CompanyKind.GEIQ,
        },
    )
