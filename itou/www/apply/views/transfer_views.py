import logging
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic.base import TemplateView

from itou.companies.models import Company
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import (
    JobApplication,
)
from itou.utils.auth import check_user
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    TransferJobApplicationForm,
)
from itou.www.apply.views.process_views import JOB_APP_DETAILS_FOR_COMPANY_BACK_URL_KEY
from itou.www.apply.views.submit_views import (
    ApplicationEndView,
    ApplicationJobsView,
    ApplicationResumeView,
    initialize_apply_session,
)
from itou.www.companies_views.views import CompanyCardView, JobDescriptionCardView
from itou.www.search_views.views import EmployerSearchView


logger = logging.getLogger(__name__)


@check_user(lambda user: user.is_employer)
def transfer(request, job_application_id):
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, pk=job_application_id)
    target_company = get_object_or_404(Company.objects, pk=request.POST.get("target_company_id"))

    session_key = JOB_APP_DETAILS_FOR_COMPANY_BACK_URL_KEY % job_application.pk
    fallback_url = request.session.get(session_key, reverse_lazy("apply:list_for_siae"))
    back_url = get_safe_url(request, "back_url", fallback_url=fallback_url)

    try:
        job_application.transfer(user=request.user, target_company=target_company)
        messages.success(
            request,
            (
                f"La candidature de {job_application.job_seeker.get_full_name()} "
                f"a bien été transférée à {target_company.display_name}||"
                "Pour la consulter, rendez-vous sur son tableau de bord en changeant de structure"
            ),
            extra_tags="toast",
        )
    except Exception as ex:
        messages.error(
            request,
            "Une erreur est survenue lors du transfert de la candidature : "
            f"{ job_application= }, { target_company= }, { ex= }",
            extra_tags="toast",
        )

    return HttpResponseRedirect(back_url)


# We need LoginRequiredMixin because EmployerSearchView inherits from LoginNotRequiredMixin
class JobApplicationExternalTransferStep1View(LoginRequiredMixin, EmployerSearchView):
    job_application = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user)
                .filter(state=job_applications_enums.JobApplicationState.REFUSED)
                .select_related("job_seeker", "to_company"),
                pk=kwargs["job_application_id"],
            )

    def dispatch(self, request, *args, **kwargs):
        if self.job_application and not request.GET:
            return HttpResponseRedirect(f"{request.path}?city={self.job_application.to_company.city_slug}")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "progress": 25,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
        }

    def get_template_names(self):
        return [
            "search/includes/siaes_search_results.html"
            if self.request.htmx
            else "apply/process_external_transfer_siaes_search_results.html"
        ]


class JobApplicationExternalTransferStep1CompanyCardView(CompanyCardView):
    def setup(self, request, job_application_id, company_pk, *args, **kwargs):
        super().setup(request, company_pk, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user),
                id=job_application_id,
            )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
        }


class JobApplicationExternalTransferStep1JobDescriptionCardView(JobDescriptionCardView):
    def setup(self, request, job_application_id, job_description_id, *args, **kwargs):
        super().setup(request, job_description_id, *args, **kwargs)

        if request.user.is_authenticated:
            self.job_application = get_object_or_404(
                JobApplication.objects.is_active_company_member(request.user),
                id=job_application_id,
            )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        return data | {
            "job_app_to_transfer": self.job_application,
            "matomo_custom_title": data["matomo_custom_title"] + " (transfert)",
            "can_update_job_description": False,
        }


@check_user(lambda user: user.is_employer)  # redondant with is_active_company_member() but more obvious
def job_application_external_transfer_start_view(request, job_application_id, company_pk, **kwargs):
    job_application = get_object_or_404(
        JobApplication.objects.is_active_company_member(request.user), pk=job_application_id
    )
    company = get_object_or_404(Company.objects.with_has_active_members(), pk=company_pk)

    if company in request.organizations:
        # This is not an external transfer
        url = reverse(
            "apply:job_application_internal_transfer",
            kwargs={"job_application_id": job_application.pk, "company_pk": company.pk},
        )
        if params := request.GET.urlencode():
            url = f"{url}?{params}"
        return HttpResponseRedirect(url)

    # It's an external transfer : initialize the apply_session
    data = {
        "reset_url": get_safe_url(request, "back_url", reverse("dashboard:index")),
        "company_pk": company.pk,
        "job_seeker_public_id": str(job_application.job_seeker.public_id),
    }
    apply_session = initialize_apply_session(request, data)

    url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "session_uuid": apply_session.name},
    )
    if params := request.GET.urlencode():
        url = f"{url}?{params}"
    return HttpResponseRedirect(url)


class ApplicationOverrideMixin:
    additionnal_related_models = []

    def setup(self, request, *args, **kwargs):
        self.job_application = get_object_or_404(
            JobApplication.objects.is_active_company_member(request.user).select_related(
                "job_seeker", "to_company", *self.additionnal_related_models
            ),
            pk=kwargs["job_application_id"],
        )
        return super().setup(request, *args, **kwargs)


class JobApplicationExternalTransferStep2View(ApplicationOverrideMixin, ApplicationJobsView):
    def get_initial(self):
        selected_jobs = []
        if job_id := self.request.GET.get("job_description_id"):
            selected_jobs.append(job_id)
        return {"selected_jobs": selected_jobs}

    def get_next_url(self):
        base_url = reverse(
            "apply:job_application_external_transfer_step_3",
            kwargs={"session_uuid": self.apply_session.name, "job_application_id": self.job_application.pk},
        )
        return f"{base_url}?back_url={quote(self.request.get_full_path())}"

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_app_to_transfer": self.job_application,
            "step": 2,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk}),
            "page_title": "Transférer la candidature",
        }

    def get_back_url(self):
        return get_safe_url(self.request, "back_url")


class JobApplicationExternalTransferStep3View(ApplicationOverrideMixin, ApplicationResumeView):
    additionnal_related_models = ["sender", "sender_company", "sender_prescriber_organization"]
    template_name = "apply/process_external_transfer_resume.html"
    form_class = TransferJobApplicationForm

    def get_initial(self):
        sender_display = self.job_application.sender.get_full_name()
        if self.job_application.sender_company:
            sender_display += f" {self.job_application.sender_company.name}"
        elif self.job_application.sender_prescriber_organization:
            sender_display += f" - {self.job_application.sender_prescriber_organization.name}"
        initial_message = (
            f"Le {self.job_application.created_at.strftime('%d/%m/%Y à %Hh%M')}, {sender_display} a écrit :\n\n"
            + self.job_application.message
        )
        return {"message": initial_message}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial = kwargs.get("initial", {})
        initial.update(self.get_initial())
        kwargs["initial"] = initial
        kwargs["original_job_application"] = self.job_application
        return kwargs

    def form_valid(self):
        new_job_application = super().form_valid()
        self.job_application.external_transfer(target_company=self.company, user=self.request.user)
        if self.form.cleaned_data.get("keep_original_resume"):
            new_job_application.resume = self.job_application.resume.copy()
            new_job_application.save(update_fields={"resume", "updated_at"})
        return new_job_application

    def get_next_url(self, job_application):
        return reverse(
            "apply:job_application_external_transfer_step_end", kwargs={"job_application_id": job_application.pk}
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_app_to_transfer": self.job_application,
            "step": 3,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk}),
            "page_title": "Transférer la candidature",
        }

    def get_back_url(self):
        return get_safe_url(self.request, "back_url")


class JobApplicationExternalTransferStepEndView(ApplicationEndView):
    def setup(self, request, *args, **kwargs):
        job_app_qs = JobApplication.objects.prescriptions_of(request.user, request.current_organization)

        job_application = get_object_or_404(job_app_qs, pk=kwargs["job_application_id"])

        return super().setup(
            request,
            *args,
            application_pk=kwargs["job_application_id"],
            company_pk=job_application.to_company_id,
            **kwargs,
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "page_title": "Candidature transférée",
        }


class JobApplicationInternalTransferView(TemplateView):
    template_name = "apply/process_internal_transfer.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.job_application = get_object_or_404(
            JobApplication.objects.is_active_company_member(request.user).select_related("job_seeker", "to_company"),
            pk=kwargs["job_application_id"],
        )
        self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=kwargs["company_pk"])

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "job_app_to_transfer": self.job_application,
            "company": self.company,
            "progress": 75,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk}),
            "back_url": get_safe_url(self.request, "back_url"),
        }
