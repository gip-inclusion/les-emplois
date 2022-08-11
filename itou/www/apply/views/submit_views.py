import functools
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.users.models import JobSeekerProfile, User
from itou.utils.perms.user import get_user_info
from itou.utils.session import SessionNamespace, SessionNamespaceRequiredMixin
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    CheckJobSeekerInfoForm,
    CheckJobSeekerNirForm,
    CreateJobSeekerStep1ForSenderForm,
    CreateJobSeekerStep2ForSenderForm,
    CreateJobSeekerStep3ForSenderForm,
    SubmitJobApplicationForm,
    UserExistsForm,
)
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


def get_approvals_wrapper(request, job_seeker, siae):
    """
    Returns an `ApprovalsWrapper` if possible or stop
    the job application submit process.
    This works only when the `job_seeker` is known.
    """
    user_info = get_user_info(request)
    approvals_wrapper = job_seeker.approvals_wrapper

    if approvals_wrapper.cannot_bypass_waiting_period(
        siae=siae, sender_prescriber_organization=user_info.prescriber_organization
    ):
        error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY
        if user_info.user == job_seeker:
            error = approvals_wrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_USER
        raise PermissionDenied(error)

    if approvals_wrapper.has_valid and approvals_wrapper.latest_approval.is_pass_iae:

        latest_approval = approvals_wrapper.latest_approval
        # Ensure that an existing approval can be unsuspended.
        if latest_approval.is_suspended and not latest_approval.can_be_unsuspended:
            error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_PROXY
            if user_info.user == job_seeker:
                error = Approval.ERROR_PASS_IAE_SUSPENDED_FOR_USER
            raise PermissionDenied(error)

    return approvals_wrapper


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
                "back_url": get_safe_url(request, "back_url"),
                "job_seeker_pk": user_info.user.pk if user_info.user.is_job_seeker else None,
                "job_seeker_email": None,
                "nir": None,
                "siae_pk": self.siae.pk,
                "sender_pk": user_info.user.pk,
                "sender_kind": user_info.kind,
                "sender_siae_pk": user_info.siae.pk if user_info.siae else None,
                "sender_prescriber_organization_pk": (
                    user_info.prescriber_organization.pk if user_info.prescriber_organization else None
                ),
                "job_description_id": request.GET.get("job_description_id"),
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
            # Redirect to search by e-mail address.
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

        preview_mode = False
        job_seeker_name = None

        if self.form.is_valid():
            job_seeker = self.form.get_job_seeker()

            # No user found with that NIR, save the NIR in the session and redirect to search by e-mail address.
            if not job_seeker:
                self.apply_session.set("nir", self.form.cleaned_data["nir"])
                return HttpResponseRedirect(reverse("apply:check_email_for_sender", kwargs={"siae_pk": self.siae.pk}))

            # Ask the sender to confirm the NIR we found is associated to the correct user
            if self.form.data.get("preview"):
                preview_mode = True
                # Don't display personal information to unauthorized members.
                if self.sender.is_prescriber and not self.sender.is_prescriber_with_authorized_org:
                    job_seeker_name = f"{job_seeker.first_name[0]}… {job_seeker.last_name[0]}…"
                else:
                    job_seeker_name = job_seeker.get_full_name()

            # The NIR we found is correct
            if self.form.data.get("confirm"):
                self.apply_session.set("job_seeker_pk", job_seeker.pk)
                return HttpResponseRedirect(
                    reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": self.siae.pk})
                )

        return self.render_to_response(
            self.get_context_data(**kwargs)
            | {
                "preview_mode": preview_mode,
                "job_seeker_name": job_seeker_name,
            }
        )

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

        return HttpResponseRedirect(reverse("apply:step_eligibility", kwargs={"siae_pk": self.siae.pk}))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "profile": self.profile,
            "progress": "80",
            "back_url": reverse(
                "apply:create_job_seeker_step_3_for_sender",
                kwargs={"siae_pk": self.siae.pk, "session_uuid": self.job_seeker_session.name},
            ),
        }


@login_required
@valid_session_required(["siae_pk"])
def step_check_job_seeker_info(request, siae_pk, template_name="apply/submit_step_job_seeker_check_info.html"):
    """
    Ensure the job seeker has all required info.
    """
    session_ns = SessionNamespace(request.session, f"job_application-{siae_pk}")
    job_seeker = get_object_or_404(User, pk=session_ns.get("job_seeker_pk"))
    siae = get_object_or_404(Siae, pk=session_ns.get("siae_pk"))
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)
    next_url = reverse("apply:step_check_prev_applications", kwargs={"siae_pk": siae_pk})

    # Check required info that will allow us to find a pre-existing approval.
    has_required_info = job_seeker.birthdate and (
        job_seeker.pole_emploi_id or job_seeker.lack_of_pole_emploi_id_reason
    )

    if has_required_info:
        return HttpResponseRedirect(next_url)

    form = CheckJobSeekerInfoForm(instance=job_seeker, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(next_url)

    context = {"form": form, "siae": siae, "job_seeker": job_seeker, "approvals_wrapper": approvals_wrapper}
    return render(request, template_name, context)


@login_required
@valid_session_required(["siae_pk"])
def step_check_prev_applications(request, siae_pk, template_name="apply/submit_step_check_prev_applications.html"):
    """
    Check previous job applications to avoid duplicates.
    """
    session_ns = SessionNamespace(request.session, f"job_application-{siae_pk}")
    siae = get_object_or_404(Siae, pk=session_ns.get("siae_pk"))
    job_seeker = get_object_or_404(User, pk=session_ns.get("job_seeker_pk"))
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)
    prev_applications = job_seeker.job_applications.filter(to_siae=siae)

    # Limit the possibility of applying to the same SIAE for 24 hours.
    if not request.user.is_siae_staff and prev_applications.created_in_past(hours=24).exists():
        if request.user == job_seeker:
            msg = "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures."
        else:
            msg = "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures."
        raise PermissionDenied(msg)

    next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})

    if not prev_applications.exists():
        return HttpResponseRedirect(next_url)

    # At this point we know that the candidate is applying to an SIAE
    # where he or she has already applied.
    # Allow a new job application if the user confirm it despite the
    # duplication warning.
    if request.method == "POST" and request.POST.get("force_new_application") == "force":
        return HttpResponseRedirect(next_url)

    context = {
        "job_seeker": job_seeker,
        "siae": siae,
        "prev_application": prev_applications.latest("created_at"),
        "approvals_wrapper": approvals_wrapper,
    }
    return render(request, template_name, context)


@login_required
@valid_session_required(["siae_pk"])
def step_eligibility(request, siae_pk, template_name="apply/submit_step_eligibility.html"):
    """
    Check eligibility (as an authorized prescriber).
    """
    session_ns = SessionNamespace(request.session, f"job_application-{siae_pk}")
    siae = get_object_or_404(Siae, pk=session_ns.get("siae_pk"))
    next_url = reverse("apply:step_application", kwargs={"siae_pk": siae_pk})

    if not siae.is_subject_to_eligibility_rules:
        return HttpResponseRedirect(next_url)

    user_info = get_user_info(request)
    job_seeker = get_object_or_404(User, pk=session_ns.get("job_seeker_pk"))
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)

    skip = (
        # Only "authorized prescribers" can perform an eligibility diagnosis.
        not user_info.is_authorized_prescriber
        # Eligibility diagnosis already performed.
        or job_seeker.has_valid_diagnosis()
    )

    if skip:
        return HttpResponseRedirect(next_url)

    data = request.POST if request.method == "POST" else None
    form_administrative_criteria = AdministrativeCriteriaForm(request.user, siae=None, data=data)

    if request.method == "POST" and form_administrative_criteria.is_valid():
        EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=form_administrative_criteria.cleaned_data
        )
        messages.success(request, "Éligibilité confirmée !")
        return HttpResponseRedirect(next_url)

    context = {
        "siae": siae,
        "job_seeker": job_seeker,
        "approvals_wrapper": approvals_wrapper,
        "form_administrative_criteria": form_administrative_criteria,
    }
    return render(request, template_name, context)


@login_required
@valid_session_required(["siae_pk"])
def step_application(request, siae_pk, template_name="apply/submit_step_application.html"):
    """
    Create and submit the job application.
    """
    queryset = Siae.objects.prefetch_job_description_through()
    siae = get_object_or_404(queryset, pk=siae_pk)

    session_ns = SessionNamespace(request.session, f"job_application-{siae_pk}")
    initial_data = {"selected_jobs": [session_ns.get("job_description_id")]}
    form = SubmitJobApplicationForm(data=request.POST or None, siae=siae, initial=initial_data)

    job_seeker = get_object_or_404(User, pk=session_ns.get("job_seeker_pk"))
    approvals_wrapper = get_approvals_wrapper(request, job_seeker, siae)

    if request.method == "POST" and form.is_valid():
        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae_pk})

        # Prevent multiple rapid clicks on the submit button to create multiple
        # job applications.
        if job_seeker.job_applications.filter(to_siae=siae).created_in_past(seconds=10).exists():
            return HttpResponseRedirect(next_url)

        job_application = form.save(commit=False)
        job_application.job_seeker = job_seeker

        job_application.sender = get_object_or_404(User, pk=session_ns.get("sender_pk"))
        job_application.sender_kind = session_ns.get("sender_kind")
        if sender_prescriber_organization_pk := session_ns.get("sender_prescriber_organization_pk"):
            job_application.sender_prescriber_organization = get_object_or_404(
                PrescriberOrganization, pk=sender_prescriber_organization_pk
            )
        if sender_siae_pk := session_ns.get("sender_siae_pk"):
            job_application.sender_siae = get_object_or_404(Siae, pk=sender_siae_pk)
        job_application.to_siae = siae
        job_application.save()

        for job in form.cleaned_data["selected_jobs"]:
            job_application.selected_jobs.add(job)

        if job_application.is_spontaneous:
            notification = NewSpontaneousJobAppEmployersNotification(job_application=job_application)
        else:
            notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)

        notification.send()
        base_url = request.build_absolute_uri("/")[:-1]
        job_application.email_new_for_job_seeker(base_url=base_url).send()

        if job_application.is_sent_by_proxy:
            job_application.email_new_for_prescriber.send()

        return HttpResponseRedirect(next_url)

    s3_upload = S3Upload(kind="resume")
    s3_form_values = s3_upload.form_values
    s3_upload_config = s3_upload.config

    context = {
        "siae": siae,
        "form": form,
        "job_seeker": job_seeker,
        "approvals_wrapper": approvals_wrapper,
        "s3_form_values": s3_form_values,
        "s3_upload_config": s3_upload_config,
    }
    return render(request, template_name, context)


class ApplicationSentView(ApplyStepBaseView):
    template_name = "apply/submit_step_application_sent.html"
    required_session_namespaces = ["apply_session"]

    def __init__(self):
        super().__init__()
        self.job_seeker = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        # Get the object early so the session is not yet deleted
        self.job_seeker = get_object_or_404(User, pk=self.apply_session.get("job_seeker_pk"))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
        }

    def get(self, request, *args, **kwargs):
        self.apply_session.delete()

        if request.user.is_siae_staff:  # TODO(rsebille) Check if we can avoid a redirection and do that part earlier
            messages.success(request, "Candidature bien envoyée !")
            return HttpResponseRedirect(reverse("apply:list_for_siae"))

        return super().get(request, *args, **kwargs)
