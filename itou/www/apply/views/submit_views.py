import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import storages
from django.forms import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from itou.approvals.models import Approval
from itou.companies import enums as companies_enums
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, JobDescription
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.files.models import File
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params
from itou.www.apply.forms import (
    ApplicationJobsForm,
    CheckJobSeekerInfoForm,
    SubmitJobApplicationForm,
)
from itou.www.apply.views import common as common_views, constants as apply_view_constants
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForm
from itou.www.job_seekers_views.forms import (
    CreateOrUpdateJobSeekerStep2Form,
)


logger = logging.getLogger(__name__)


JOB_SEEKER_INFOS_CHECK_PERIOD = relativedelta(months=6)


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

    if job_seeker_public_id := request.GET.get("job_seeker"):
        try:
            job_seeker = User.objects.filter(kind=UserKind.JOB_SEEKER, public_id=job_seeker_public_id).get()
        except (
            ValidationError,
            User.DoesNotExist,
        ):
            raise Http404("Aucun candidat n'a été trouvé.")
    return job_seeker


class ApplyStepBaseView(LoginRequiredMixin, TemplateView):
    def __init__(self):
        super().__init__()
        self.company = None
        self.apply_session = None
        self.hire_process = None
        self.prescription_process = None
        self.auto_prescription_process = None
        self.is_gps = False

    def setup(self, request, *args, **kwargs):
        self.is_gps = "gps" in request.GET and request.GET["gps"] == "true"
        self.company = (
            get_object_or_404(Company.objects.with_has_active_members(), pk=kwargs["company_pk"])
            if not self.is_gps
            else Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)
        )
        self.apply_session = SessionNamespace(request.session, f"job_application-{self.company.pk}")
        self.hire_process = kwargs.pop("hire_process", False)
        self.prescription_process = (
            not self.hire_process
            and request.user.is_authenticated
            and (
                request.user.is_prescriber
                or (request.user.is_employer and self.company != request.current_organization)
            )
        )
        self.auto_prescription_process = (
            not self.hire_process
            and request.user.is_authenticated
            and request.user.is_employer
            and self.company == request.current_organization
        )

        super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if not self.is_gps:
            if request.user.is_authenticated:
                if self.hire_process and request.user.kind != UserKind.EMPLOYER:
                    raise PermissionDenied("Seuls les employeurs sont autorisés à déclarer des embauches")
                elif self.hire_process and not self.company.has_member(request.user):
                    raise PermissionDenied("Vous ne pouvez déclarer une embauche que dans votre structure.")
                elif request.user.kind not in [
                    UserKind.JOB_SEEKER,
                    UserKind.PRESCRIBER,
                    UserKind.EMPLOYER,
                ]:
                    raise PermissionDenied("Vous n'êtes pas autorisé à déposer de candidature.")

            if not self.company.has_active_members:
                raise PermissionDenied(
                    "Cet employeur n'est pas inscrit, vous ne pouvez pas déposer de candidatures en ligne."
                )
        return super().dispatch(request, *args, **kwargs)

    def get_back_url(self):
        return None

    def get_reset_url(self):
        if self.hire_process or self.auto_prescription_process:
            # The employer can come either by creating an application or hiring somebody.
            # In both cases, the reset_url adds no value compared to going back to the dashboard.
            return reverse("dashboard:index")

        try:
            selected_jobs = self.apply_session.get("selected_jobs", [])
            [job_description] = selected_jobs
        except (
            KeyError,  # No apply_session
            ValueError,  # No job description, or multiple job descriptions.
        ):
            return reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
        return reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description})

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "siae": self.company,
            "back_url": self.get_back_url(),
            "hire_process": self.hire_process,
            "prescription_process": self.prescription_process,
            "auto_prescription_process": self.auto_prescription_process,
            "reset_url": self.get_reset_url(),
            "is_gps": self.is_gps,
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
        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return

        self.job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=kwargs["job_seeker_public_id"]
        )
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

    def redirect_to_check_infos(self, job_seeker_public_id):
        view_name = "apply:check_job_seeker_info_for_hire" if self.hire_process else "apply:step_check_job_seeker_info"
        return HttpResponseRedirect(
            reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": job_seeker_public_id})
        )


class StartView(ApplyStepBaseView):
    def get(self, request, *args, **kwargs):
        tunnel = "job_seeker" if request.user.is_job_seeker else "sender"

        if not self.is_gps:
            # Checks are not relevants for the creation of a job_seeker in the GPS context
            # because we don't create a job application, only a job_seeker and a job_seeker_profile

            if self.auto_prescription_process or self.hire_process:
                if suspension_explanation := self.company.get_active_suspension_text_with_dates():
                    raise PermissionDenied(
                        "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle "
                        "a posteriori. " + suspension_explanation
                    )

            # Refuse all applications except those made by an SIAE member
            if self.company.block_job_applications and not self.company.has_member(request.user):
                raise Http404("Cette organisation n'accepte plus de candidatures pour le moment.")

        # Store away the selected job in the session to avoid passing it
        # along the many views before ApplicationJobsView.
        if job_description_id := request.GET.get("job_description_id"):
            try:
                job_description = self.company.job_description_through.active().get(pk=job_description_id)
            except (JobDescription.DoesNotExist, ValueError):
                pass
            else:
                self.apply_session.init({"selected_jobs": [job_description.pk]})

        # Go directly to step ApplicationJobsView if we're carrying the job seeker public id with us.
        if tunnel == "sender" and (job_seeker := _get_job_seeker_to_apply_for(self.request)):
            return HttpResponseRedirect(
                add_url_params(
                    reverse(
                        "apply:application_jobs",
                        kwargs={"company_pk": self.company.pk, "job_seeker_public_id": job_seeker.public_id},
                    ),
                    {"job_description_id": job_description_id},
                )
            )

        # Warn message if prescriber's authorization is pending
        if (
            request.user.is_prescriber
            and request.current_organization
            and request.current_organization.has_pending_authorization()
            and not self.is_gps
        ):
            return HttpResponseRedirect(
                reverse("apply:pending_authorization_for_sender", kwargs={"company_pk": self.company.pk})
            )

        return HttpResponseRedirect(
            reverse(f"job_seekers_views:check_nir_for_{tunnel}", kwargs={"company_pk": self.company.pk})
            + ("?gps=true" if self.is_gps else "")
        )


class PendingAuthorizationForSender(ApplyStepForSenderBaseView):
    template_name = "apply/submit_step_pending_authorization.html"


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
            "back_url": reverse("job_seekers_views:check_nir_for_hire", kwargs={"company_pk": self.company.pk}),
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
        return reverse(
            view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id}
        )

    def get(self, request, *args, **kwargs):
        if not self.previous_applications.exists():
            return HttpResponseRedirect(self.get_next_url())

        # Limit the possibility of applying to the same SIAE for 24 hours.
        if (
            not (self.auto_prescription_process or self.hire_process)
            and self.previous_applications.created_in_past(hours=24).exists()
        ):
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

    def get_initial(self):
        return {"selected_jobs": self.apply_session.get("selected_jobs", [])}

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if not self.apply_session.exists():
            self.apply_session.init({})

        self.form = ApplicationJobsForm(
            self.company,
            initial=self.get_initial(),
            data=request.POST or None,
        )

    def get_next_url(self):
        # dispatching to IAE or GEIQ eligibility
        path_name = (
            "application_geiq_eligibility" if self.company.kind == CompanyKind.GEIQ else "application_eligibility"
        )
        return reverse(
            "apply:" + path_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
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


class RequireApplySessionMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.apply_session.exists():
            return HttpResponseRedirect(
                reverse(
                    "apply:application_jobs",
                    kwargs={
                        "company_pk": self.company.pk,
                        "job_seeker_public_id": self.job_seeker.public_id,
                    },
                )
            )
        return super().dispatch(request, *args, **kwargs)


class ApplicationEligibilityView(RequireApplySessionMixin, ApplicationBaseView):
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
            "apply:application_resume",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
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
                # No need for eligibility diagnosis if the job seeker already have a PASS IAE
                self.job_seeker.has_valid_approval,
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
                "apply:application_jobs",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            ),
            "full_content_width": True,
        }


class ApplicationGEIQEligibilityView(RequireApplySessionMixin, ApplicationBaseView):
    template_name = "apply/submit/application/geiq_eligibility.html"

    def __init__(self):
        super().__init__()

        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return

        if self.company.kind != CompanyKind.GEIQ:
            raise Http404("This form is only for GEIQ")

        self.form = GEIQAdministrativeCriteriaForm(
            company=self.company,
            administrative_criteria=(
                self.geiq_eligibility_diagnosis.administrative_criteria.all()
                if self.geiq_eligibility_diagnosis
                else []
            ),
            form_url=reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            ),
            data=request.POST or None,
        )

    def get_next_url(self):
        return reverse(
            "apply:application_resume",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
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
                "apply:application_jobs",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
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


class ApplicationResumeView(RequireApplySessionMixin, ApplicationBaseView):
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

        if not request.user.is_authenticated:
            # Do nothing, LoginRequiredMixin will raise in dispatch()
            return

        self.form = self.form_class(**self.get_form_kwargs())

    def get_next_url(self, job_application):
        return reverse(
            "apply:application_end",
            kwargs={"company_pk": self.company.pk, "application_pk": job_application.pk},
        )

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
            File.objects.create(key=key)
            public_storage = storages["public"]
            name = public_storage.save(key, resume)
            job_application.resume_link = public_storage.url(name)

        # Save the job application
        job_application.save()
        selected_jobs = self.company.job_description_through.filter(
            is_active=True,
            pk__in=self.apply_session.get("selected_jobs", []),
        )
        job_application.selected_jobs.set(selected_jobs)
        # The job application is now saved in DB, delete the session early to avoid any problems
        self.apply_session.delete()

        try:
            # Send notifications
            company_recipients = User.objects.filter(
                companymembership__company=job_application.to_company,
                companymembership__is_active=True,
            )
            for employer in company_recipients:
                job_application.notifications_new_for_employer(employer).send()
            job_application.notifications_new_for_job_seeker.send()
            if self.request.user.is_prescriber:
                job_application.notifications_new_for_proxy.send()
        finally:
            # We are done, send to the (mostly) stateless final page as we now have no session.
            # "company_pk" is kinda useless with "application_pk" but is kept for URL consistency.
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
                # No need for eligibility diagnosis if the job seeker already have a PASS IAE
                self.job_seeker.has_valid_approval,
            ]
            if not any(bypass_eligibility_conditions):
                view_name = "apply:application_eligibility"

        return reverse(
            view_name,
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
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
            "reset_url": reverse(
                "apply:application_end",
                kwargs={"company_pk": self.company.pk, "application_pk": self.job_application.pk},
            ),
            "page_title": "Auto-prescription enregistrée" if self.auto_prescription_process else "Candidature envoyée",
        }


@login_required
def eligibility_for_hire(
    request,
    company_pk,
    job_seeker_public_id,
    template_name="apply/submit/eligibility_for_hire.html",
):
    company = get_object_or_404(Company.objects.member_required(request.user), pk=company_pk)
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id)
    _check_job_seeker_approval(request, job_seeker, company)
    next_url = reverse(
        "apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
    )
    bypass_eligibility_conditions = [
        # Don't perform an eligibility diagnosis is the SIAE doesn't need it,
        not company.is_subject_to_eligibility_rules,
        # No need for eligibility diagnosis if the job seeker already has a PASS IAE
        job_seeker.has_valid_approval,
    ]
    if any(bypass_eligibility_conditions) or job_seeker.has_valid_diagnosis(for_siae=company):
        return HttpResponseRedirect(next_url)
    return common_views._eligibility(
        request,
        company,
        job_seeker,
        cancel_url=reverse(
            "apply:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        ),
        next_url=next_url,
        template_name=template_name,
        extra_context={"hire_process": True},
    )


@login_required
def geiq_eligibility_for_hire(
    request,
    company_pk,
    job_seeker_public_id,
    template_name="apply/submit/geiq_eligibility_for_hire.html",
):
    company = get_object_or_404(
        Company.objects.member_required(request.user).filter(kind=CompanyKind.GEIQ), pk=company_pk
    )
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id)
    next_url = reverse(
        "apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
    )
    if GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, company).exists():
        return HttpResponseRedirect(next_url)
    return common_views._geiq_eligibility(
        request,
        company,
        job_seeker,
        back_url=reverse(
            "apply:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        ),
        next_url=next_url,
        geiq_eligibility_criteria_url=reverse(
            "apply:geiq_eligibility_criteria_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        ),
        template_name=template_name,
        extra_context={
            "hire_process": True,
            "is_subject_to_eligibility_rules": False,
        },
    )


@login_required
def geiq_eligibility_criteria_for_hire(request, company_pk, job_seeker_public_id):
    company = get_object_or_404(
        Company.objects.member_required(request.user).filter(kind=CompanyKind.GEIQ), pk=company_pk
    )
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=job_seeker_public_id)
    return common_views._geiq_eligibility_criteria(
        request,
        company,
        job_seeker,
    )


@login_required
def hire_confirmation(
    request,
    company_pk,
    job_seeker_public_id,
    template_name="apply/submit/hire_confirmation.html",
):
    company = get_object_or_404(Company.objects.member_required(request.user), pk=company_pk)
    job_seeker = get_object_or_404(
        User.objects.filter(kind=UserKind.JOB_SEEKER).select_related("jobseeker_profile"),
        public_id=job_seeker_public_id,
    )
    if company.kind == CompanyKind.GEIQ:
        geiq_eligibility_diagnosis = (
            GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, company)
            .prefetch_related("selected_administrative_criteria__administrative_criteria")
            .first()
        )
        if geiq_eligibility_diagnosis:
            geiq_eligibility_diagnosis.criteria_display = geiq_eligibility_diagnosis.get_criteria_display_qs()
        eligibility_diagnosis = None

    else:
        _check_job_seeker_approval(request, job_seeker, company)
        # General IAE eligibility case
        eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker, for_siae=company, prefetch=["selected_administrative_criteria__administrative_criteria"]
        )
        if eligibility_diagnosis is not None:
            # The job_seeker object already contains a lot of information: no need to re-retrieve it
            eligibility_diagnosis.job_seeker = job_seeker
            eligibility_diagnosis.criteria_display = eligibility_diagnosis.get_criteria_display_qs()
        geiq_eligibility_diagnosis = None

    return common_views._accept(
        request,
        company,
        job_seeker,
        error_url=reverse(
            "apply:hire_confirmation", kwargs={"company_pk": company_pk, "job_seeker_public_id": job_seeker_public_id}
        ),
        back_url=reverse(
            "apply:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        ),
        template_name=template_name,
        extra_context={
            "can_edit_personal_information": request.user.can_edit_personal_information(job_seeker),
            "is_subject_to_eligibility_rules": company.is_subject_to_eligibility_rules,
            "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
            "eligibility_diagnosis": eligibility_diagnosis,
            "expired_eligibility_diagnosis": None,  # XXX: should we search for an expired diagnosis here ?
            "is_subject_to_geiq_eligibility_rules": company.kind == CompanyKind.GEIQ,
        },
    )


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
                self.can_view_personal_information = request.user.can_view_personal_information(self.job_seeker)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_seeker": self.job_seeker,
            "exit_url": self.exit_url,
            "can_view_personal_information": self.can_view_personal_information,
        }

    def get_job_seeker_query_string(self):
        return {"job_seeker": self.request.GET.get("job_seeker")} if self.request.GET.get("job_seeker", None) else {}
