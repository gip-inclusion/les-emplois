import functools
import logging

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.siaes.models import Siae, SiaeJobDescription
from itou.users.models import JobSeekerProfile, User
from itou.utils.perms.user import get_user_info
from itou.utils.session import SessionNamespace, SessionNamespaceRequiredMixin
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    ApplicationJobsForm,
    CheckJobSeekerInfoForm,
    CheckJobSeekerNirForm,
    CreateJobSeekerStep1ForSenderForm,
    CreateJobSeekerStep2ForSenderForm,
    CreateJobSeekerStep3ForSenderForm,
    SubmitJobApplicationForm,
    UserExistsForm,
)
from itou.www.apply.views import constants as apply_view_constants
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


logger = logging.getLogger(__name__)


def valid_session_required(required_keys=None):
    def wrapper(function):
        @functools.wraps(function)
        def decorated(request, *args, **kwargs):
            session_ns = SessionNamespace(request.session, f"job_application-{kwargs['siae_pk']}")
            if not session_ns.exists():
                return HttpResponseRedirect(reverse("siaes_views:card", kwargs={"siae_id": kwargs["siae_pk"]}))
            if required_keys:
                for key in required_keys:
                    if session_ns.get(key) != kwargs[key]:
                        raise PermissionDenied("missing session data information", key)
            return function(request, *args, **kwargs)

        return decorated

    return wrapper


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
        if request.user.is_authenticated and not any(
            [request.user.is_job_seeker, request.user.is_prescriber, request.user.is_siae_staff]
        ):
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

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_seeker = get_object_or_404(User, pk=self.apply_session.get("job_seeker_pk"))
        _check_job_seeker_approval(request, self.job_seeker, self.siae)
        self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
            self.job_seeker, for_siae=self.siae
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
            "eligibility_diagnosis": self.eligibility_diagnosis,
            "is_subject_to_eligibility_rules": self.siae.is_subject_to_eligibility_rules,
            "can_edit_personal_information": self.request.user.can_edit_personal_information(self.job_seeker),
            "can_view_personal_information": self.request.user.can_view_personal_information(self.job_seeker),
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

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if not any([self.sender.is_prescriber, self.sender.is_siae_staff]):
            return HttpResponseRedirect(reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))
        return super().dispatch(request, *args, **kwargs)


class StartView(ApplyStepBaseView):
    def _coalesce_back_url(self):
        if "back_url" in self.request.GET:
            return get_safe_url(self.request, "back_url")
        if job_description_id := self.request.GET.get("job_description_id"):
            return reverse("siaes_views:job_description_card", kwargs={"job_description_id": job_description_id})
        return reverse("siaes_views:card", kwargs={"siae_id": self.siae.pk})

    def get(self, request, *args, **kwargs):
        # SIAE members can only submit a job application to their SIAE
        if request.user.is_siae_staff and not self.siae.has_member(request.user):
            raise PermissionDenied("Vous ne pouvez postuler pour un candidat que dans votre structure.")

        # Refuse all applications except those made by an SIAE member
        if self.siae.block_job_applications and not self.siae.has_member(request.user):
            raise Http404("Cette organisation n'accepte plus de candidatures pour le moment.")

        # Create a sub-session for this job application process
        user_info = get_user_info(request)
        self.apply_session.init(
            {
                "back_url": self._coalesce_back_url(),
                "job_seeker_pk": user_info.user.pk if user_info.user.is_job_seeker else None,
                "job_seeker_email": None,
                "nir": None,
                "siae_pk": self.siae.pk,
                "sender_pk": user_info.user.pk,
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
            return HttpResponseRedirect(reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk}))

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.data.get("skip"):
            return HttpResponseRedirect(reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk}))

        if self.form.is_valid():
            self.job_seeker.nir = self.form.cleaned_data["nir"]
            self.job_seeker.save()
            return HttpResponseRedirect(reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk}))

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

    def post(self, request, *args, **kwargs):
        if self.form.data.get("skip"):
            # Redirect to search by e-mail address.
            return HttpResponseRedirect(reverse("apply:check_email_for_sender", kwargs={"siae_pk": self.siae.pk}))

        context = {}
        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                self.apply_session.set("nir", self.form.cleaned_data["nir"])
                return HttpResponseRedirect(reverse("apply:check_email_for_sender", kwargs={"siae_pk": self.siae.pk}))

            # The NIR we found is correct
            if self.form.data.get("confirm"):
                self.apply_session.set("job_seeker_pk", job_seeker.pk)
                return HttpResponseRedirect(
                    reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk})
                )

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
            "form_action": reverse("apply:check_nir_for_sender", kwargs={"siae_pk": self.siae.pk}),
        }


class CheckEmailForSenderView(ApplyStepForSenderBaseView):
    template_name = "apply/submit_step_job_seeker.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = UserExistsForm(data=request.POST or None)

    def post(self, request, *args, **kwargs):
        can_add_nir = False
        preview_mode = False
        job_seeker_name = None

        if self.form.is_valid():
            job_seeker = self.form.get_user()
            nir = self.apply_session.get("nir")
            can_add_nir = nir and self.sender.can_add_nir(job_seeker)

            # No user found with that email, redirect to create a new account.
            if not job_seeker:
                job_seeker_session = SessionNamespace.create_temporary(request.session)
                job_seeker_session.init({"user": {"email": self.form.cleaned_data["email"], "nir": nir}})
                return HttpResponseRedirect(
                    reverse(
                        "apply:create_job_seeker_step_1_for_sender",
                        kwargs={"siae_pk": self.siae.pk, "session_uuid": job_seeker_session.name},
                    )
                )

            # Ask the sender to confirm the email we found is associated to the correct user
            if self.form.data.get("preview"):
                preview_mode = True
                # Don't display personal information to unauthorized members.
                if self.sender.is_prescriber and not self.sender.is_prescriber_with_authorized_org:
                    job_seeker_name = f"{job_seeker.first_name[0]}… {job_seeker.last_name[0]}…"
                else:
                    job_seeker_name = job_seeker.get_full_name()

            # The email we found is correct
            if self.form.data.get("confirm"):
                self.apply_session.set("job_seeker_pk", job_seeker.pk)

                if not can_add_nir:
                    return HttpResponseRedirect(
                        reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk})
                    )

                try:
                    job_seeker.nir = self.apply_session.get("nir")
                    job_seeker.save(update_fields=["nir"])
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
                    return HttpResponseRedirect(
                        reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk})
                    )

        return self.render_to_response(
            self.get_context_data(**kwargs)
            | {
                "can_add_nir": can_add_nir,
                "preview_mode": preview_mode,
                "job_seeker_name": job_seeker_name,
            }
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "nir": self.apply_session.get("nir"),
            "siae": self.siae,
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
    template_name = "apply/submit/create_job_seeker_for_sender/step_1.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CreateJobSeekerStep1ForSenderForm(
            data=request.POST or None, initial=self.job_seeker_session.get("user", {})
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.job_seeker_session.set("user", self.job_seeker_session.get("user", {}) | self.form.cleaned_data)
            return HttpResponseRedirect(
                reverse(
                    "apply:create_job_seeker_step_2_for_sender",
                    kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
                )
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "progress": "20",
        }


class CreateJobSeekerStep2ForSenderView(CreateJobSeekerForSenderBaseView):
    template_name = "apply/submit/create_job_seeker_for_sender/step_2.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = CreateJobSeekerStep2ForSenderForm(
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
    template_name = "apply/submit/create_job_seeker_for_sender/step_3.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = CreateJobSeekerStep3ForSenderForm(
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
    template_name = "apply/submit/create_job_seeker_for_sender/step_end.html"

    def __init__(self):
        super().__init__()
        self.profile = None

    def _get_user_data_from_session(self):
        return {k: v for k, v in self.job_seeker_session.get("user").items() if k not in ["city_slug"]}

    def _get_profile_data_from_session(self):
        # Dummy fields used by CreateJobSeekerStep3ForSenderForm()
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

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        profile = JobSeekerProfile(
            user=User.create_job_seeker_by_proxy(self.sender, **self._get_user_data_from_session()),
            **self._get_profile_data_from_session(),
        )
        profile.save()

        self.apply_session.set("job_seeker_pk", profile.user.pk)
        self.job_seeker_session.delete()  # Point of no return

        return HttpResponseRedirect(reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk}))

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
                reverse("apply:step_check_prev_applications", kwargs={"siae_pk": self.siae.pk})
            )

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.form.save()
            return HttpResponseRedirect(
                reverse("apply:step_check_prev_applications", kwargs={"siae_pk": self.siae.pk})
            )

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "can_view_personal_information": self.request.user.can_view_personal_information(self.job_seeker),
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
            return HttpResponseRedirect(reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk}))

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
            return HttpResponseRedirect(reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk}))

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "prev_application": self.previous_applications.latest("created_at"),
            "can_view_personal_information": self.request.user.can_view_personal_information(self.job_seeker),
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
            return HttpResponseRedirect(reverse("apply:application_eligibility", kwargs={"siae_pk": self.siae.pk}))

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

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

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
            return HttpResponseRedirect(reverse("apply:application_resume", kwargs={"siae_pk": self.siae.pk}))

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            user_info = get_user_info(request)
            if not self.eligibility_diagnosis:
                EligibilityDiagnosis.create_diagnosis(self.job_seeker, user_info, self.form.cleaned_data)
            elif self.eligibility_diagnosis and not self.form.data.get("shrouded"):
                EligibilityDiagnosis.update_diagnosis(self.eligibility_diagnosis, user_info, self.form.cleaned_data)
            return HttpResponseRedirect(reverse("apply:application_resume", kwargs={"siae_pk": self.siae.pk}))

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        new_expires_at_if_updated = timezone.now() + relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS)
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "new_expires_at_if_updated": new_expires_at_if_updated,
            "progress": 50,
            "back_url": reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk}),
        }


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
                kwargs={"siae_pk": self.siae.pk},
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
        self.form = CreateJobSeekerStep2ForSenderForm(
            instance=self.job_application.job_seeker, data=request.POST or None
        )

    def post(self, request, *args, **kwargs):
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
