import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.storage import storages
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, JobDescription
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.utils import geiq_criteria_for_display, iae_criteria_for_display
from itou.files.models import File
from itou.gps.models import FollowUpGroup
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.utils import can_edit_personal_information, can_view_personal_information
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params, get_safe_url
from itou.www.apply.forms import ApplicationJobsForm, SubmitJobApplicationForm
from itou.www.apply.views import common as common_views, constants as apply_view_constants
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForm
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from itou.www.job_seekers_views.forms import CreateOrUpdateJobSeekerStep2Form


logger = logging.getLogger(__name__)


JOB_SEEKER_INFOS_CHECK_PERIOD = relativedelta(months=6)

APPLY_SESSION_KIND = "apply_session"


def _check_job_seeker_approval(request, job_seeker, siae):
    if job_seeker.new_approval_blocked_by_waiting_period(
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


def _get_job_seeker_to_apply_for(request):
    job_seeker = None

    if job_seeker_public_id := request.GET.get("job_seeker_public_id"):
        try:
            job_seeker = User.objects.filter(kind=UserKind.JOB_SEEKER, public_id=job_seeker_public_id).get()
        except (
            ValidationError,
            User.DoesNotExist,
        ):
            raise Http404("Aucun candidat n'a été trouvé.")
    return job_seeker


def initialize_apply_session(request, data):
    return SessionNamespace.create_uuid_namespace(request.session, APPLY_SESSION_KIND, data)


class ApplicationPermissionMixin:
    """
    This mixin requires the following arguments that must be setup by the child view

    company: Company
    hire_process: bool
    auto_prescription_process: bool
    """

    def get_reset_url(self):
        raise NotImplementedError

    def dispatch(self, request, *args, **kwargs):
        if self.hire_process and request.user.kind != UserKind.EMPLOYER:
            raise PermissionDenied("Seuls les employeurs sont autorisés à déclarer des embauches")
        if self.hire_process and not self.company.has_member(request.user):
            raise PermissionDenied("Vous ne pouvez déclarer une embauche que dans votre structure.")
        if request.user.kind not in [
            UserKind.JOB_SEEKER,
            UserKind.PRESCRIBER,
            UserKind.EMPLOYER,
        ]:
            raise PermissionDenied("Vous n'êtes pas autorisé à déposer de candidature.")
        if not self.company.has_active_members:
            raise PermissionDenied(
                "Cet employeur n'est pas inscrit, vous ne pouvez pas déposer de candidatures en ligne."
            )
        if self.auto_prescription_process or self.hire_process:
            if suspension_explanation := self.company.get_active_suspension_text_with_dates():
                raise PermissionDenied(
                    "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle "
                    "a posteriori. " + suspension_explanation
                )
        # Refuse all applications except those made by an SIAE member
        if self.company.block_job_applications and not self.company.has_member(request.user):
            messages.error(request, apply_view_constants.ERROR_EMPLOYER_BLOCKING_APPLICATIONS)
            return HttpResponseRedirect(self.get_reset_url())
        # Limit the possibility of applying to the same SIAE for 24 hours.
        if (
            hasattr(self, "job_seeker")
            and not (self.auto_prescription_process or self.hire_process)
            and self.get_previous_applications_queryset().created_in_past(hours=24).exists()
        ):
            if request.user == self.job_seeker:
                msg = "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures."
            else:
                msg = "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures."
            self.apply_session.delete()  # Don't allow to re-use the session in another step to skip this check
            raise PermissionDenied(msg)
        return super().dispatch(request, *args, **kwargs)

    def get_previous_applications_queryset(self):
        # Also used in CheckPreviousApplications
        return self.job_seeker.job_applications.filter(to_company=self.company)


class StartView(ApplicationPermissionMixin, View):
    def setup(self, request, company_pk, *args, hire_process=False, **kwargs):
        super().setup(request, *args, **kwargs)

        self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=company_pk)
        self.hire_process = hire_process
        self.auto_prescription_process = (
            not self.hire_process and request.user.is_employer and self.company == request.current_organization
        )
        self.reset_url = get_safe_url(request, "back_url", reverse("dashboard:index"))

    def get_reset_url(self):
        return self.reset_url

    def init_job_seeker_session(self, request):
        job_seeker_session = SessionNamespace.create_uuid_namespace(
            request.session,
            JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER,
            data={
                "config": {
                    "from_url": self.get_reset_url(),
                },
                "apply": {
                    "session_uuid": self.apply_session.name,
                    "company_pk": self.company.pk,
                },
            },
        )
        return job_seeker_session

    def get(self, request, *args, **kwargs):
        session_data = {"reset_url": self.reset_url, "company_pk": self.company.pk}
        # Store away the selected job in the session to avoid passing it
        # along the many views before ApplicationJobsView.
        if job_description_id := request.GET.get("job_description_id"):
            try:
                job_description = self.company.job_description_through.active().get(pk=job_description_id)
            except (JobDescription.DoesNotExist, ValueError):
                pass
            else:
                session_data["selected_jobs"] = [job_description.pk]

        job_seeker = _get_job_seeker_to_apply_for(self.request)
        if job_seeker:
            session_data["job_seeker_public_id"] = str(job_seeker.public_id)

        self.apply_session = initialize_apply_session(request, session_data)

        if request.user.is_job_seeker:
            tunnel = "job_seeker"
        elif self.hire_process:
            tunnel = "hire"
        else:
            tunnel = "sender"

        # Go directly to step ApplicationJobsView if we're carrying the job seeker public id with us.
        if tunnel == "sender" and job_seeker:
            return HttpResponseRedirect(
                add_url_params(
                    reverse("apply:application_jobs", kwargs={"session_uuid": self.apply_session.name}),
                    {"job_description_id": job_description_id},
                )
            )

        # Warn message if prescriber's authorization is pending
        if (
            request.user.is_prescriber
            and request.current_organization
            and request.current_organization.has_pending_authorization()
        ):
            return HttpResponseRedirect(
                reverse("apply:pending_authorization_for_sender", kwargs={"session_uuid": self.apply_session.name})
            )

        if tunnel == "job_seeker":
            # Init a job_seeker_session needed for job_seekers_views
            job_seeker_session = self.init_job_seeker_session(request)

            return HttpResponseRedirect(
                reverse("job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session.name})
            )

        params = {
            "tunnel": tunnel,
            "apply_session_uuid": self.apply_session.name,
            "company": self.company.pk,
            "from_url": self.get_reset_url(),
        }

        next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        return HttpResponseRedirect(next_url)


class RequireApplySessionMixin:
    def __init__(self):
        self.apply_session = None

    def setup(self, request, *args, session_uuid, **kwargs):
        super().setup(request, *args, **kwargs)

        self.apply_session = SessionNamespace(request.session, APPLY_SESSION_KIND, session_uuid)
        if not self.apply_session.exists():
            raise Http404

    def get_reset_url(self):
        return self.apply_session.get("reset_url")

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "reset_url": self.get_reset_url(),
        }


class ApplyStepBaseView(RequireApplySessionMixin, ApplicationPermissionMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.company = None
        self.hire_process = None
        self.prescription_process = None
        self.auto_prescription_process = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.company = get_object_or_404(
            Company.objects.with_has_active_members(), pk=self.apply_session.get("company_pk")
        )
        self.hire_process = kwargs.pop("hire_process", False)
        self.prescription_process = not self.hire_process and (
            request.user.is_prescriber or (request.user.is_employer and self.company != request.current_organization)
        )
        self.auto_prescription_process = (
            not self.hire_process and request.user.is_employer and self.company == request.current_organization
        )

    def get_back_url(self):
        return None

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "siae": self.company,
            "back_url": self.get_back_url(),
            "hire_process": self.hire_process,
            "prescription_process": self.prescription_process,
            "auto_prescription_process": self.auto_prescription_process,
            "page_title": "Postuler",
        }


class ApplicationBaseView(ApplyStepBaseView):
    def __init__(self):
        super().__init__()

        self.job_seeker = None
        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        job_seeker_public_id = self.apply_session.get("job_seeker_public_id") or request.GET.get(
            "job_seeker_public_id"
        )
        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id
        )
        if "job_seeker_public_id" not in self.apply_session:
            self.apply_session.set("job_seeker_public_id", job_seeker_public_id)
        _check_job_seeker_approval(request, self.job_seeker, self.company)
        # Prescribers do not see employer diagnosis.
        for_company = self.company if self.request.user.is_employer else None
        if self.company.kind == CompanyKind.GEIQ:
            self.geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
                self.job_seeker, for_company
            ).first()
        elif self.company.is_subject_to_eligibility_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, for_company
            )

    def get_eligibility_step_url(self):
        if self.company.kind == CompanyKind.GEIQ and self.request.from_authorized_prescriber:
            return reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": self.apply_session.name})
        if self.company.kind != CompanyKind.GEIQ:
            bypass_eligibility_conditions = [
                # Don't perform an eligibility diagnosis if the SIAE doesn't need it
                not self.company.is_subject_to_eligibility_rules,
                # Only "authorized prescribers" can perform an eligibility diagnosis
                not self.request.from_authorized_prescriber,
                # No need for eligibility diagnosis if the job seeker already has a PASS IAE
                self.job_seeker.has_valid_approval,
            ]
            if not any(bypass_eligibility_conditions):
                return reverse("eligibility_views:update", kwargs={"session_uuid": self.apply_session.name})
        return None

    def get_eligibility_for_hire_step_url(self):
        if self.company.kind == CompanyKind.GEIQ and not self.geiq_eligibility_diagnosis:
            return reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": self.apply_session.name})

        bypass_eligibility_conditions = [
            # Don't perform an eligibility diagnosis if the SIAE doesn't need it,
            not self.company.is_subject_to_eligibility_rules,
            # No need for eligibility diagnosis if the job seeker already has a PASS IAE
            self.job_seeker.has_valid_approval,
            # Job seeker must not have a diagnosis
            self.eligibility_diagnosis,
        ]
        if not any(bypass_eligibility_conditions):
            return reverse("apply:eligibility_for_hire", kwargs={"session_uuid": self.apply_session.name})

        return None

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
            "eligibility_diagnosis": self.eligibility_diagnosis,
            "is_subject_to_eligibility_rules": self.company.is_subject_to_eligibility_rules,
            "geiq_eligibility_diagnosis": self.geiq_eligibility_diagnosis,
            "is_subject_to_geiq_eligibility_rules": self.company.kind == CompanyKind.GEIQ,
            "can_edit_personal_information": can_edit_personal_information(self.request, self.job_seeker),
            "can_view_personal_information": can_view_personal_information(self.request, self.job_seeker),
            # Do not show the warning for job seekers
            "new_check_needed": (
                not self.request.user.is_job_seeker
                and self.job_seeker.last_checked_at < timezone.now() - JOB_SEEKER_INFOS_CHECK_PERIOD
            ),
        }


class ApplyStepForSenderBaseView(ApplyStepBaseView):
    def __init__(self):
        super().__init__()
        self.sender = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.sender = request.user

    def dispatch(self, request, *args, **kwargs):
        if self.sender.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            logger.info(f"dispatch ({request.path}) : {self.sender.kind} in sender tunnel")
            return HttpResponseRedirect(reverse("apply:start", kwargs={"company_pk": self.company.pk}))
        return super().dispatch(request, *args, **kwargs)


class PendingAuthorizationForSender(ApplyStepForSenderBaseView):
    template_name = "apply/submit_step_pending_authorization.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        params = {
            "tunnel": "sender",
            "company": self.company.pk,
            "from_url": self.get_reset_url(),
            "apply_session_uuid": self.apply_session.name,
        }
        self.next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {"next_url": self.next_url}


class CheckPreviousApplications(ApplicationBaseView):
    """
    Check previous job applications to avoid duplicates.
    """

    template_name = "apply/submit_step_check_prev_applications.html"

    def get_next_url(self):
        if self.hire_process:
            return self.get_eligibility_for_hire_step_url() or reverse(
                "apply:hire_confirmation", kwargs={"session_uuid": self.apply_session.name}
            )
        else:
            view_name = "apply:application_jobs"
        return reverse(view_name, kwargs={"session_uuid": self.apply_session.name})

    def get(self, request, *args, **kwargs):
        if not self.get_previous_applications_queryset().exists():
            return HttpResponseRedirect(self.get_next_url())
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        # At this point we know that the candidate is applying to an SIAE where he or she has already applied.
        # Allow a new job application if the user confirm it despite the duplication warning.
        if request.POST.get("force_new_application") == "force":
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "prev_application": self.get_previous_applications_queryset().latest("created_at"),
        }


class ApplicationJobsView(ApplicationBaseView):
    template_name = "apply/submit/application/jobs.html"

    def __init__(self):
        super().__init__()
        self.form = None

    def get_initial(self):
        return {"selected_jobs": self.apply_session.get("selected_jobs", [])}

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.form = ApplicationJobsForm(
            self.company,
            initial=self.get_initial(),
            data=request.POST or None,
        )

    def get_next_url(self):
        return self.get_eligibility_step_url() or reverse(
            "apply:application_resume", kwargs={"session_uuid": self.apply_session.name}
        )

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.apply_session.set("selected_jobs", self.form.cleaned_data.get("selected_jobs", []))
            return HttpResponseRedirect(self.get_next_url())

        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        job_descriptions_by_pk = {jd.pk: jd for jd in self.form.fields["selected_jobs"].queryset}
        return super().get_context_data(**kwargs) | {
            "form": self.form,
            "job_descriptions_by_pk": job_descriptions_by_pk,
            "progress": 25,
            "full_content_width": bool(job_descriptions_by_pk),
        }


class CheckApplySessionMixin:
    def get_redirect_url(self):
        return reverse("apply:application_jobs", kwargs={"session_uuid": self.apply_session.name})

    def dispatch(self, request, *args, **kwargs):
        # Application must not be blocked by the employer at time of access
        # self.company.block_job_applications is handled in ApplicationPermissionMixin
        if not self.company.has_member(request.user) and not self.company.block_job_applications:
            # Spontaneous application blocked
            if (
                not self.apply_session.get("selected_jobs", [])
                and not self.company.is_open_to_spontaneous_applications
            ):
                messages.error(request, apply_view_constants.ERROR_EMPLOYER_BLOCKING_SPONTANEOUS_APPLICATIONS)
                return HttpResponseRedirect(self.get_redirect_url())

            # One of the selected jobs is now inactive
            if self.company.job_description_through.filter(
                is_active=False,
                pk__in=self.apply_session.get("selected_jobs", []),
            ).exists():
                messages.error(request, apply_view_constants.ERROR_EMPLOYER_BLOCKING_APPLICATIONS_FOR_JOB_DESCRIPTION)
                return HttpResponseRedirect(self.get_redirect_url())

        return super().dispatch(request, *args, **kwargs)


class ApplicationEligibilityView(CheckApplySessionMixin, ApplicationBaseView):
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
            request.from_authorized_prescriber,
            siae=self.company,
            initial=initial_data,
            data=request.POST or None,
        )

    def get_next_url(self):
        return reverse("apply:application_resume", kwargs={"session_uuid": self.apply_session.name})

    def dispatch(self, request, *args, **kwargs):
        if self.get_eligibility_step_url() is None:
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
        context = super().get_context_data(**kwargs)
        context["form"] = self.form
        context["progress"] = 50
        context["job_seeker"] = self.job_seeker
        context["back_url"] = reverse("apply:application_jobs", kwargs={"session_uuid": self.apply_session.name})
        context["full_content_width"] = True
        if self.eligibility_diagnosis:
            context["new_expires_at_if_updated"] = self.eligibility_diagnosis._expiration_date(self.request.user)
        return context


class ApplicationGEIQEligibilityView(CheckApplySessionMixin, ApplicationBaseView):
    template_name = "apply/submit/application/geiq_eligibility.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.company.kind != CompanyKind.GEIQ:
            raise Http404("This form is only for GEIQ")

        self.form = GEIQAdministrativeCriteriaForm(
            company=self.company,
            administrative_criteria=(
                self.geiq_eligibility_diagnosis.administrative_criteria.all()
                if self.geiq_eligibility_diagnosis
                else []
            ),
            form_url=reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": self.apply_session.name}),
            data=request.POST or None,
        )

    def get_next_url(self):
        return reverse("apply:application_resume", kwargs={"session_uuid": self.apply_session.name})

    def dispatch(self, request, *args, **kwargs):
        if self.get_eligibility_step_url() is None:
            return HttpResponseRedirect(self.get_next_url())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        geo_criteria_detected = self.job_seeker.address_in_qpv or self.job_seeker.zrr_city_name
        return super().get_context_data(**kwargs) | {
            "back_url": reverse("apply:application_jobs", kwargs={"session_uuid": self.apply_session.name}),
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


class ApplicationResumeView(CheckApplySessionMixin, ApplicationBaseView):
    template_name = "apply/submit/application/resume.html"
    form_class = SubmitJobApplicationForm

    def __init__(self):
        super().__init__()

        self.form = None

    def get_form_kwargs(self):
        return {
            "company": self.company,
            "user": self.request.user,
            "auto_prescription_process": self.auto_prescription_process,
            "data": self.request.POST or None,
            "files": self.request.FILES or None,
        }

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.form = self.form_class(**self.get_form_kwargs())

    def get_next_url(self, job_application):
        return reverse("apply:application_end", kwargs={"application_pk": job_application.pk})

    def form_valid(self):
        # Fill the job application with the required information
        job_application = JobApplication(
            job_seeker=self.job_seeker,
            to_company=self.company,
            sender=self.request.user,
            sender_kind=self.request.user.kind,
            message=self.form.cleaned_data["message"],
        )
        if self.request.user.is_prescriber:
            job_application.sender_prescriber_organization = self.request.current_organization
        if self.request.user.is_employer:
            job_application.sender_company = self.request.current_organization

        if resume := self.form.cleaned_data.get("resume"):
            key = f"resume/{uuid.uuid4()}.pdf"
            file_resume = File.objects.create(key=key)
            storages["public"].save(key, resume)
            job_application.resume = file_resume

        # Save the job application
        job_application.save()
        selected_jobs = self.company.job_description_through.filter(
            is_active=True,
            pk__in=self.apply_session.get("selected_jobs", []),
        )
        job_application.selected_jobs.set(selected_jobs)
        # The job application is now saved in DB, delete the session early to avoid any problems
        self.apply_session.delete()

        if self.request.user.is_employer or self.request.user.is_prescriber:
            # New job application -> sync GPS groups if the sender is not a jobseeker
            FollowUpGroup.objects.follow_beneficiary(self.job_seeker, self.request.user)

        # Send notifications
        company_recipients = job_application.to_company.active_members.all()
        for employer in company_recipients:
            job_application.notifications_new_for_employer(employer).send()
        job_application.notifications_new_for_job_seeker.send()
        if self.request.user.kind in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            job_application.notifications_new_for_proxy.send()
        return job_application

    def post(self, request, *args, **kwargs):
        # Prevent multiple rapid clicks on the submit button to create multiple job applications.
        job_application = (
            self.job_seeker.job_applications.filter(to_company=self.company).created_in_past(seconds=10).first()
        )
        if job_application:
            return HttpResponseRedirect(self.get_next_url(job_application))
        if self.form.is_valid():
            job_application = self.form_valid()
            return HttpResponseRedirect(self.get_next_url(job_application))
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_back_url(self):
        return self.get_eligibility_step_url() or reverse(
            "apply:application_jobs", kwargs={"session_uuid": self.apply_session.name}
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


class ApplicationEndView(TemplateView):
    template_name = "apply/submit/application/end.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_application = get_object_or_404(
            JobApplication.objects.select_related("job_seeker", "to_company"),
            pk=kwargs.get("application_pk"),
            sender=request.user,
        )
        self.company = self.job_application.to_company
        self.form = CreateOrUpdateJobSeekerStep2Form(
            instance=self.job_application.job_seeker, data=request.POST or None
        )
        self.auto_prescription_process = request.user.is_employer and self.company == request.current_organization

    def post(self, request, *args, **kwargs):
        if not can_edit_personal_information(self.request, self.job_application.job_seeker):
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
            "can_edit_personal_information": can_edit_personal_information(
                self.request, self.job_application.job_seeker
            ),
            "can_view_personal_information": can_view_personal_information(
                self.request, self.job_application.job_seeker
            ),
            "reset_url": reverse("apply:application_end", kwargs={"application_pk": self.job_application.pk}),
            "page_title": "Auto-prescription enregistrée" if self.auto_prescription_process else "Candidature envoyée",
        }


class IAEEligibilityForHireView(ApplicationBaseView, common_views.BaseIAEEligibilityView):
    template_name = "apply/submit/eligibility_for_hire.html"

    def dispatch(self, request, *args, **kwargs):
        if self.get_eligibility_for_hire_step_url() is None:
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.apply_session.name})

    def get_cancel_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hire_process"] = True
        return context


class GEIQEligibilityForHireView(ApplicationBaseView, common_views.BaseGEIQEligibilityView):
    template_name = "apply/submit/geiq_eligibility_for_hire.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.geiq_eligibility_criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def dispatch(self, request, *args, **kwargs):
        if self.get_eligibility_for_hire_step_url() is None:
            return HttpResponseRedirect(self.get_next_url())
        return super().dispatch(request, *args, **kwargs)

    def get_next_url(self):
        return reverse("apply:hire_confirmation", kwargs={"session_uuid": self.apply_session.name})

    def get_back_url(self):
        return reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hire_process"] = True
        context["is_subject_to_eligibility_rules"] = False
        return context


class GEIQEligiblityCriteriaForHireView(ApplicationBaseView, common_views.BaseGEIQEligibilityCriteriaHtmxView):
    pass


class HireConfirmationView(ApplicationBaseView, common_views.BaseAcceptView):
    template_name = "apply/submit/hire_confirmation.html"

    def setup(self, request, *args, **kwargs):
        self.job_application = None
        return super().setup(request, *args, **kwargs)

    def clean_session(self):
        self.apply_session.delete()

    def get_back_url(self):
        return self.get_eligibility_for_hire_step_url() or reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": self.apply_session.name}
        )

    def get_error_url(self):
        return self.request.get_full_path()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.geiq_eligibility_diagnosis:
            self.geiq_eligibility_diagnosis.criteria_display = geiq_criteria_for_display(
                self.geiq_eligibility_diagnosis
            )
        if self.eligibility_diagnosis:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            self.eligibility_diagnosis.job_seeker = self.job_seeker
            self.eligibility_diagnosis.criteria_display = iae_criteria_for_display(self.eligibility_diagnosis)

        context["can_edit_personal_information"] = can_edit_personal_information(self.request, self.job_seeker)
        context["is_subject_to_eligibility_rules"] = self.company.is_subject_to_eligibility_rules
        context["geiq_eligibility_diagnosis"] = self.geiq_eligibility_diagnosis
        context["eligibility_diagnosis"] = self.eligibility_diagnosis
        context["expired_eligibility_diagnosis"] = None  # XXX: should we search for an expired diagnosis here ?
        context["is_subject_to_geiq_eligibility_rules"] = self.company.kind == CompanyKind.GEIQ

        return context


class ApplyForJobSeekerMixin:
    def __init__(self):
        super().__init__()
        self.job_seeker = None
        self.exit_url = None
        self.can_view_personal_information = False

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_seeker = None
        self.exit_url = reverse("home:hp")
        self.can_view_personal_information = False

        if request.user.is_authenticated and request.user.kind in (
            UserKind.PRESCRIBER,
            UserKind.EMPLOYER,
        ):
            if request.user.is_prescriber:
                self.exit_url = reverse("job_seekers_views:list")
            elif request.user.is_employer:
                self.exit_url = reverse("apply:list_prescriptions")

            self.job_seeker = _get_job_seeker_to_apply_for(request)
            if self.job_seeker:
                self.can_view_personal_information = can_view_personal_information(request, self.job_seeker)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
            "exit_url": self.exit_url,
            "can_view_personal_information": self.can_view_personal_information,
        }

    def get_job_seeker_query_string(self):
        job_seeker_public_id = self.request.GET.get("job_seeker_public_id")
        return {"job_seeker_public_id": job_seeker_public_id} if job_seeker_public_id else {}
