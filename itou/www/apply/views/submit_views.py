import logging

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.siaes.enums import SiaeKind
from itou.siaes.models import Siae, SiaeJobDescription
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis.exceptions import AddressLookupError
from itou.utils.emails import redact_email_address
from itou.utils.perms.user import get_user_info
from itou.utils.session import SessionNamespace, SessionNamespaceRequiredMixin
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
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
from itou.www.apply.views import constants as apply_view_constants
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForm


logger = logging.getLogger(__name__)


JOB_SEEKER_INFOS_CHECK_PERIOD = relativedelta(months=6)


def _check_job_seeker_approval(request, job_seeker, siae):
    user_info = get_user_info(request)
    if job_seeker.approval_can_be_renewed_by(
        siae=siae, sender_prescriber_organization=user_info.prescriber_organization
    ):
        # NOTE(vperron): We're using PermissionDenied in order to display a message to the end user
        # by reusing the 403 template and its logic. I'm not 100% sure that this is a good idea but,
        # it's not too bad so far. I'd personnally would have raised a custom base error and caught it
        # somewhere using a middleware to display an error page that is not linked to a 403.
        if user_info.user == job_seeker:
            error = apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_USER
        else:
            error = apply_view_constants.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        raise PermissionDenied(error)

    approval = job_seeker.latest_approval
    if approval and approval.is_valid():
        # Ensure that an existing approval can be unsuspended.
        if approval.is_suspended and not approval.can_be_unsuspended:
            error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_PROXY
            if user_info.user == job_seeker:
                error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_USER
            raise PermissionDenied(error)


class ApplyStepBaseView(LoginRequiredMixin, SessionNamespaceRequiredMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.siae = None
        self.apply_session = None

    def setup(self, request, *args, **kwargs):
        self.siae = get_object_or_404(Siae, pk=kwargs["siae_pk"])
        self.apply_session = SessionNamespace(request.session, f"job_application-{self.siae.pk}")
        super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.kind not in [
            UserKind.JOB_SEEKER,
            UserKind.PRESCRIBER,
            UserKind.SIAE_STAFF,
        ]:
            raise PermissionDenied("Vous n'êtes pas autorisé à déposer de candidature.")
        return super().dispatch(request, *args, **kwargs)

    def get_back_url(self):
        if not self.apply_session.exists():
            return None

        if session_back_url := self.apply_session.get("back_url"):
            return get_safe_url(request=self.request, url=session_back_url)
        return None

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "siae": self.siae,
            "back_url": self.get_back_url(),
        }


class ApplicationBaseView(ApplyStepBaseView):
    required_session_namespaces = ["apply_session"]

    def __init__(self):
        super().__init__()

        self.job_seeker = None
        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.job_seeker = get_object_or_404(User, pk=kwargs["job_seeker_pk"])
        _check_job_seeker_approval(request, self.job_seeker, self.siae)
        if self.siae.kind == SiaeKind.GEIQ:
            self.geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.job_seeker, self.siae
            ).first()
        else:
            # General IAE eligibility case
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, for_siae=self.siae
            )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
            "eligibility_diagnosis": self.eligibility_diagnosis,
            "is_subject_to_eligibility_rules": self.siae.is_subject_to_eligibility_rules,
            "geiq_eligibility_diagnosis": self.geiq_eligibility_diagnosis,
            "is_subject_to_geiq_eligibility_rules": self.siae.kind == SiaeKind.GEIQ,
            "can_edit_personal_information": self.request.user.can_edit_personal_information(self.job_seeker),
            "can_view_personal_information": self.request.user.can_view_personal_information(self.job_seeker),
            # Do not show the warning for job seekers
            "new_check_needed": (
                not self.request.user.is_job_seeker
                and self.job_seeker.last_checked_at < timezone.now() - JOB_SEEKER_INFOS_CHECK_PERIOD
            ),
        }


class ApplyStepForJobSeekerBaseView(ApplyStepBaseView):
    required_session_namespaces = ["apply_session"]

    def __init__(self):
        super().__init__()
        self.job_seeker = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.job_seeker = request.user

    def dispatch(self, request, *args, **kwargs):
        if not self.job_seeker.is_job_seeker:
            return HttpResponseRedirect(reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
        }


class ApplyStepForSenderBaseView(ApplyStepBaseView):
    required_session_namespaces = ["apply_session"]

    def __init__(self):
        super().__init__()
        self.sender = None
        self.process = None

    def setup(self, request, *args, **kwargs):
        if process := kwargs.pop("process", None):
            self.process = process
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if self.sender.kind not in [UserKind.PRESCRIBER, UserKind.SIAE_STAFF]:
            return HttpResponseRedirect(reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))
        return super().dispatch(request, *args, **kwargs)

    def redirect_to_check_infos(self, job_seeker_pk):
        return HttpResponseRedirect(
            reverse(
                "apply:check_infos_for_hire" if self.process == "hire" else "apply:step_check_job_seeker_info",
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": job_seeker_pk},
            )
        )


class StartView(ApplyStepBaseView):
    def _coalesce_back_url(self):
        if "back_url" in self.request.GET:
            return get_safe_url(self.request, "back_url")
        if job_description_id := self.request.GET.get("job_description_id"):
            return reverse("siaes_views:job_description_card", kwargs={"job_description_id": job_description_id})
        return reverse("siaes_views:card", kwargs={"siae_id": self.siae.pk})

    def get(self, request, *args, **kwargs):
        # SIAE members can only submit a job application to their SIAE
        if request.user.is_siae_staff:
            if not self.siae.has_member(request.user):
                raise PermissionDenied("Vous ne pouvez postuler pour un candidat que dans votre structure.")
            if suspension_explanation := self.siae.get_active_suspension_text_with_dates():
                raise PermissionDenied(
                    "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle "
                    "a posteriori. " + suspension_explanation
                )

        # Refuse all applications except those made by an SIAE member
        if self.siae.block_job_applications and not self.siae.has_member(request.user):
            raise Http404("Cette organisation n'accepte plus de candidatures pour le moment.")

        # Create a sub-session for this job application process
        user_info = get_user_info(request)
        self.apply_session.init(
            {
                "back_url": self._coalesce_back_url(),
                "selected_jobs": [request.GET["job_description_id"]] if "job_description_id" in request.GET else [],
            }
        )
        # Warn message if prescriber's authorization is pending
        if user_info.prescriber_organization and user_info.prescriber_organization.has_pending_authorization():
            return HttpResponseRedirect(
                reverse("apply:pending_authorization_for_sender", kwargs={"siae_pk": self.siae.pk})
            )

        tunnel = "job_seeker" if user_info.user.is_job_seeker else "sender"
        return HttpResponseRedirect(reverse(f"apply:check_nir_for_{tunnel}", kwargs={"siae_pk": self.siae.pk}))


class PendingAuthorizationForSender(ApplyStepForSenderBaseView):
    template_name = "apply/submit_step_pending_authorization.html"


class CheckNIRForJobSeekerView(ApplyStepForJobSeekerBaseView):
    template_name = "apply/submit_step_check_job_seeker_nir.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CheckJobSeekerNirForm(job_seeker=self.job_seeker, data=request.POST or None)

    def get(self, request, *args, **kwargs):
        # The NIR already exists, go to next step
        if self.job_seeker.nir:
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.data.get("skip"):
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        if self.form.is_valid():
            self.job_seeker.nir = self.form.cleaned_data["nir"]
            self.job_seeker.lack_of_nir_reason = ""
            self.job_seeker.save()
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_job_seeker_info",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "form_action": reverse("apply:check_nir_for_job_seeker", kwargs={"siae_pk": self.siae.pk}),
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
        return HttpResponseRedirect(
            reverse(
                "apply:search_by_email_for_hire" if self.process == "hire" else "apply:search_by_email_for_sender",
                kwargs={"siae_pk": self.siae.pk, "session_uuid": session_uuid},
            )
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
            "form_action": (
                reverse("apply:check_nir_for_hire", kwargs={"siae_pk": self.siae.pk})
                if self.process == "hire"
                else reverse("apply:check_nir_for_sender", kwargs={"siae_pk": self.siae.pk})
            ),
            "process": self.process,
        }


class SearchByEmailForSenderView(ApplyStepForSenderBaseView):
    required_session_namespaces = ApplyStepForSenderBaseView.required_session_namespaces + ["job_seeker_session"]
    template_name = "apply/submit_step_job_seeker.html"

    def __init__(self):
        super().__init__()
        self.form = None
        self.process = None

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
                return HttpResponseRedirect(
                    reverse(
                        "apply:create_job_seeker_step_1_for_sender",
                        kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
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
                    msg = mark_safe(
                        f"Le<b> numéro de sécurité sociale</b> renseigné ({ nir }) est "
                        "déjà utilisé par un autre candidat sur la Plateforme.<br>"
                        "Merci de renseigner <b>le numéro personnel et unique</b> "
                        "du candidat pour lequel vous souhaitez postuler."
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

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "nir": self.job_seeker_session.get("user", {}).get("nir"),
            "siae": self.siae,
            "back_url": (
                reverse("apply:check_nir_for_hire", kwargs={"siae_pk": self.siae.pk})
                if self.process == "hire"
                else reverse("apply:check_nir_for_sender", kwargs={"siae_pk": self.siae.pk})
            ),
        }


class CreateJobSeekerForSenderBaseView(ApplyStepForSenderBaseView):
    required_session_namespaces = ApplyStepForSenderBaseView.required_session_namespaces + ["job_seeker_session"]

    def __init__(self):
        super().__init__()
        self.job_seeker_session = None

    def setup(self, request, *args, **kwargs):
        self.job_seeker_session = SessionNamespace(request.session, kwargs["session_uuid"])
        super().setup(request, *args, **kwargs)


class CreateJobSeekerStep1ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_1.html"

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
                return HttpResponseRedirect(
                    reverse(
                        "apply:create_job_seeker_step_2_for_sender",
                        kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
                    )
                )

        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "20",
            "back_url": reverse(
                "apply:search_by_email_for_sender",
                kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
            ),
        }


class CreateJobSeekerStep2ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_2.html"

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
            return HttpResponseRedirect(
                reverse(
                    "apply:create_job_seeker_step_3_for_sender",
                    kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "40",
            "back_url": reverse(
                "apply:create_job_seeker_step_1_for_sender",
                kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
            ),
        }


class CreateJobSeekerStep3ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_3.html"

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
            return HttpResponseRedirect(
                reverse(
                    "apply:create_job_seeker_step_end_for_sender",
                    kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "60",
            "back_url": reverse(
                "apply:create_job_seeker_step_2_for_sender",
                kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
            ),
        }


class CreateJobSeekerStepEndForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_end.html"

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

    def post(self, request, *args, **kwargs):
        try:
            user = User.create_job_seeker_by_proxy(self.sender, **self._get_user_data_from_session())
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            url = reverse("dashboard:index")
        else:
            profile = user.jobseeker_profile
            for k, v in self._get_profile_data_from_session().items():
                setattr(profile, k, v)
            profile.save()

            try:
                user.set_coords(user.address_line_1, user.post_code)
            except AddressLookupError:
                # Nothing to do: re-raised and already logged as error
                pass
            else:
                user.save()

            self.job_seeker_session.delete()
            url = reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": profile.user.pk})
        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.profile,
            "progress": "80",
            "back_url": reverse(
                "apply:create_job_seeker_step_3_for_sender",
                kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
            ),
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
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.form.save()
            return HttpResponseRedirect(
                reverse(
                    "apply:step_check_prev_applications",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
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

        self.previous_applications = self.job_seeker.job_applications.filter(to_siae=self.siae)

    def get(self, request, *args, **kwargs):
        if not self.previous_applications.exists():
            return HttpResponseRedirect(
                reverse(
                    "apply:application_jobs", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
                )
            )

        # Limit the possibility of applying to the same SIAE for 24 hours.
        if not request.user.is_siae_staff and self.previous_applications.created_in_past(hours=24).exists():
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
            return HttpResponseRedirect(
                reverse(
                    "apply:application_jobs", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
                )
            )

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

        self.form = ApplicationJobsForm(
            self.siae,
            initial={"selected_jobs": self.apply_session.get("selected_jobs", [])},
            data=request.POST or None,
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.apply_session.set("selected_jobs", self.form.cleaned_data.get("selected_jobs", []))
            # dispatching to IAE or GEIQ eligibility
            path_name = (
                "application_geiq_eligibility" if self.siae.kind == SiaeKind.GEIQ else "application_eligibility"
            )
            return HttpResponseRedirect(
                reverse("apply:" + path_name, kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk})
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


class ApplicationEligibilityView(ApplicationBaseView):
    template_name = "apply/submit/application/eligibility.html"

    def __init__(self):
        super().__init__()

        self.form = None
        self.process = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if process := kwargs.pop("process", None):
            self.process = process

        initial_data = {}

        if self.eligibility_diagnosis:
            initial_data["administrative_criteria"] = self.eligibility_diagnosis.administrative_criteria.all()

        self.form = AdministrativeCriteriaForm(
            request.user,
            siae=self.siae,
            initial=initial_data,
            data=request.POST or None,
        )

    def dispatch(self, request, *args, **kwargs):
        bypass_eligibility_conditions = [
            # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
            not self.siae.is_subject_to_eligibility_rules,
            # Only "authorized prescribers" can perform an eligibility diagnosis.
            not get_user_info(request).is_authorized_prescriber,
            # No need for eligibility diagnosis if the job seeker already have a PASS IAE
            self.job_seeker.has_valid_common_approval,
        ]
        if any(bypass_eligibility_conditions):
            return HttpResponseRedirect(self.get_next_url())

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            user_info = get_user_info(request)
            if not self.eligibility_diagnosis:
                EligibilityDiagnosis.create_diagnosis(self.job_seeker, user_info, self.form.cleaned_data)
            elif self.eligibility_diagnosis and not self.form.data.get("shrouded"):
                EligibilityDiagnosis.update_diagnosis(self.eligibility_diagnosis, user_info, self.form.cleaned_data)
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_back_url(self):
        if self.process == "hire":
            return reverse("apply:hire_infos", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk})
        return reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk})

    def get_next_url(self):
        if self.process == "hire":
            return reverse("apply:confirm_hire", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk})
        return reverse(
            "apply:application_resume", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
        )

    def get_context_data(self, **kwargs):
        new_expires_at_if_updated = timezone.now() + relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS)

        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "new_expires_at_if_updated": new_expires_at_if_updated,
            "progress": 50,
            "job_seeker": self.job_seeker,
            "back_url": self.get_back_url(),
            "full_content_width": True,
        }


class ApplicationGEIQEligibilityView(ApplicationBaseView):
    template_name = "apply/submit/application/geiq_eligibility.html"

    def __init__(self):
        super().__init__()

        self.form = None
        self.geiq_author_structure = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = GEIQAdministrativeCriteriaForm(
            siae=self.siae,
            administrative_criteria=(
                self.geiq_eligibility_diagnosis.administrative_criteria.all()
                if self.geiq_eligibility_diagnosis
                else []
            ),
            form_url=reverse(
                "apply:application_geiq_eligibility",
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
            data=request.POST or None,
        )

    def dispatch(self, request, *args, **kwargs):
        # GEIQ eligibility form during job application process is only available to authorized prescribers
        if not request.user.is_prescriber_with_authorized_org:
            return HttpResponseRedirect(
                reverse(
                    "apply:application_resume", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
                )
            )

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        geo_criteria_detected = self.job_seeker.address_in_qpv or self.job_seeker.zrr_city_name
        return super().get_context_data(**kwargs) | {
            "back_url": reverse(
                "apply:application_jobs", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
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
            user_info = get_user_info(request)
            if not self.geiq_eligibility_diagnosis:
                GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
                    self.job_seeker,
                    user_info.user,
                    user_info.prescriber_organization,
                    self.form.cleaned_data,
                )
            else:
                # Check if update is really needed: may change diagnosis expiration date
                if self.form.has_changed():
                    GEIQEligibilityDiagnosis.update_eligibility_diagnosis(
                        self.geiq_eligibility_diagnosis, request.user, self.form.cleaned_data
                    )

            return HttpResponseRedirect(
                reverse(
                    "apply:application_resume", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))


class ApplicationResumeView(ApplicationBaseView):
    template_name = "apply/submit/application/resume.html"

    def __init__(self):
        super().__init__()

        self.form = None
        self.s3_upload = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = SubmitJobApplicationForm(
            siae=self.siae,
            user=request.user,
            initial={"selected_jobs": self.apply_session.get("selected_jobs", [])},
            data=request.POST or None,
        )
        self.s3_upload = S3Upload(kind="resume")

    def dispatch(self, request, *args, **kwargs):
        # Prevent multiple rapid clicks on the submit button to create multiple job applications.
        job_application = (
            self.job_seeker.job_applications.filter(to_siae=self.siae).created_in_past(seconds=10).first()
        )
        if job_application:
            return HttpResponseRedirect(
                reverse(
                    "apply:application_end", kwargs={"siae_pk": self.siae.pk, "application_pk": job_application.pk}
                )
            )

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            # Fill the job application with the required information
            job_application = self.form.save(commit=False)
            job_application.job_seeker = self.job_seeker
            job_application.to_siae = self.siae

            sender_info = get_user_info(request)
            job_application.sender = sender_info.user
            job_application.sender_kind = sender_info.kind
            if sender_info.prescriber_organization:
                job_application.sender_prescriber_organization = sender_info.prescriber_organization
            if sender_info.siae:
                job_application.sender_siae = sender_info.siae

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
                job_application.email_new_for_job_seeker().send()

                if job_application.is_sent_by_proxy:
                    job_application.email_new_for_prescriber.send()
            finally:
                # We are done, send to the (mostly) stateless final page as we now have no session.
                # "siae_pk" is kinda useless with "application_pk" but is kept for URL consistency.
                return HttpResponseRedirect(
                    reverse(
                        "apply:application_end", kwargs={"siae_pk": self.siae.pk, "application_pk": job_application.pk}
                    )
                )
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        bypass_eligibility_conditions = [
            # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
            not self.siae.is_subject_to_eligibility_rules,
            # Only "authorized prescribers" can perform an eligibility diagnosis.
            not get_user_info(self.request).is_authorized_prescriber,
            # No need for eligibility diagnosis if the job seeker already have a PASS IAE
            self.job_seeker.has_valid_common_approval,
        ]
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "s3_upload": self.s3_upload,
            "resume_is_recommended": any(
                SiaeJobDescription.objects.filter(pk__in=self.apply_session.get("selected_jobs", [])).values_list(
                    "is_resume_mandatory", flat=True
                )
            ),
            "back_url": reverse(
                f"apply:application_{'jobs' if any(bypass_eligibility_conditions) else 'eligibility'}",
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
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
            JobApplication.objects.select_related("job_seeker", "to_siae"),
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


class UpdateJobSeekerBaseView(ApplyStepBaseView):
    required_session_namespaces = ["apply_session"]

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
        }

    def _disable_form(self):
        for field in self.form:
            field.field.disabled = True


class UpdateJobSeekerStep1View(UpdateJobSeekerBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_1.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
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
            return HttpResponseRedirect(
                reverse(
                    "apply:update_job_seeker_step_2",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )
        if self.form.is_valid():
            self.job_seeker_session.set("user", self.job_seeker_session.get("user", {}) | self.form.cleaned_data)
            return HttpResponseRedirect(
                reverse(
                    "apply:update_job_seeker_step_2",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

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
            return HttpResponseRedirect(
                reverse(
                    "apply:update_job_seeker_step_3",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )
        if self.form.is_valid():
            self.job_seeker_session.set("user", self.job_seeker_session.get("user") | self.form.cleaned_data)
            return HttpResponseRedirect(
                reverse(
                    "apply:update_job_seeker_step_3",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "readonly_form": not self.request.user.can_edit_personal_information(self.job_seeker),
            "progress": "40",
            "back_url": reverse(
                "apply:update_job_seeker_step_1",
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
        }


class UpdateJobSeekerStep3View(UpdateJobSeekerBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_3.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

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
            return HttpResponseRedirect(
                reverse(
                    "apply:update_job_seeker_step_end",
                    kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "60",
            "back_url": reverse(
                "apply:update_job_seeker_step_2",
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
        }


class UpdateJobSeekerStepEndView(UpdateJobSeekerBaseView):
    template_name = "apply/submit/create_or_update_job_seeker/step_end.html"
    required_session_namespaces = ["job_seeker_session"] + UpdateJobSeekerBaseView.required_session_namespaces

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
        return {k: v for k, v in self.job_seeker_session.get("profile").items() if k not in fields_to_exclude}

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
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
            )
        else:
            self.profile.save()
            self.job_seeker_session.delete()
            url = reverse(
                "apply:application_jobs", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
            )
        return HttpResponseRedirect(url)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.profile,
            "progress": "80",
            "back_url": reverse(
                "apply:update_job_seeker_step_3",
                kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
        }


@login_required
@user_passes_test(lambda u: u.is_siae_staff, login_url="/", redirect_field_name=None)
def check_infos_for_hire(request, siae_pk, job_seeker_pk):
    siae = get_object_or_404(Siae, pk=siae_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    geiq_eligibility_diagnosis = None
    eligibility_diagnosis = None
    if siae.kind == SiaeKind.GEIQ:
        geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, siae).first()
    else:
        # General IAE eligibility case
        eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(job_seeker, for_siae=siae)

    if not job_seeker.has_jobseeker_profile:
        profile = JobSeekerProfile(user=job_seeker)
    else:
        profile = job_seeker.jobseeker_profile
    context = {
        "siae": siae,
        "job_seeker": job_seeker,
        "profile": profile,
        "breadcrumbs": {"Déclarer une embauche": ""},
        "eligibility_diagnosis": eligibility_diagnosis,
        "is_subject_to_eligibility_rules": siae.is_subject_to_eligibility_rules,
        "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        "is_subject_to_geiq_eligibility_rules": siae.kind == SiaeKind.GEIQ,
    }
    return render(request, "apply/hire/check_infos.html", context)


@login_required
@user_passes_test(lambda u: u.is_siae_staff, login_url="/", redirect_field_name=None)
def check_prev_applications_for_hire(request, siae_pk, job_seeker_pk):
    siae = get_object_or_404(Siae, pk=siae_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    previous_applications = job_seeker.job_applications.filter(to_siae=siae)
    if not previous_applications.exists() or request.POST.get("force_new_application") == "force":
        return HttpResponseRedirect(
            reverse("apply:hire_infos", kwargs={"siae_pk": siae.pk, "job_seeker_pk": job_seeker.pk})
        )
    return render(
        request,
        "apply/hire/check_prev_applications.html",
        {
            "siae": siae,
            "job_seeker": job_seeker,
            "prev_application": previous_applications.latest("created_at"),
        },
    )


@login_required
@user_passes_test(lambda u: u.is_siae_staff, login_url="/", redirect_field_name=None)
def hire_infos(request, siae_pk, job_seeker_pk):
    siae = get_object_or_404(Siae, pk=siae_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    apply_session = SessionNamespace(request.session, f"job_application-{siae.pk}")
    apply_session.init({})
    return render(
        request,
        "apply/hire/infos.html",
        {
            "siae": siae,
            "job_seeker": job_seeker,
            "can_view_personal_information": request.user.can_view_personal_information(job_seeker),
        },
    )


@login_required
@user_passes_test(lambda u: u.is_siae_staff, login_url="/", redirect_field_name=None)
def confirm_hire(request, siae_pk, job_seeker_pk):
    siae = get_object_or_404(Siae, pk=siae_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
    return render(
        request,
        "apply/hire/confirmation.html",
        {
            "siae": siae,
            "job_seeker": job_seeker,
            "can_view_personal_information": request.user.can_view_personal_information(job_seeker),
        },
    )
