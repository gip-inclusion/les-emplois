from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.generic import FormView, TemplateView
from django_htmx.http import HttpResponseClientRedirect
from django_xworkflows import models as xwf_models

from itou.asp.forms import BirthPlaceWithoutBirthdateModelForm
from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.companies.enums import CompanyKind, ContractType
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.utils import geiq_allowance_amount
from itou.users.enums import UserKind
from itou.utils import constants as global_constants
from itou.utils.htmx import hx_trigger_modal_control
from itou.utils.urls import add_url_params, get_external_link_markup, get_safe_url
from itou.www.apply.forms import (
    AcceptForm,
    CheckJobSeekerGEIQEligibilityForm,
    JobSeekerPersonalDataForm,
)
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForGEIQForm


class CommonUserInfoFormsMixin:
    def get_session(self):
        raise NotImplementedError

    def get_forms(self):
        forms = {}
        session = self.get_session()
        if session is None:
            session_forms_data = {}
        else:
            session_forms_data = session.get("job_seeker_info_forms_data", {})

        if self.company.is_subject_to_iae_rules:
            # Info that will be used to search for an existing Pôle emploi approval.
            forms["personal_data"] = JobSeekerPersonalDataForm(
                instance=self.job_seeker,
                initial=session_forms_data.get("personal_data", {}),
                data=self.request.POST or None,
                back_url=self.request.get_full_path(),
            )
            if not self.job_seeker.address_on_one_line:
                forms["user_address"] = JobSeekerAddressForm(
                    instance=self.job_seeker,
                    initial=session_forms_data.get("user_address", {}),
                    data=self.request.POST or None,
                )
        elif self.company.kind == CompanyKind.GEIQ:
            forms["birth_place"] = BirthPlaceWithoutBirthdateModelForm(
                instance=self.job_seeker.jobseeker_profile,
                initial=session_forms_data.get("birth_place", {}),
                birthdate=self.job_seeker.jobseeker_profile.birthdate,
                data=self.request.POST or None,
            )

        return forms


class BaseFillJobSeekerInfosView(UserPassesTestMixin, CommonUserInfoFormsMixin, TemplateView):
    template_name = None

    def test_func(self):
        return self.request.user.is_employer

    def get_back_url(self):
        raise NotImplementedError

    def get_success_url(self):
        raise NotImplementedError

    def get_context_data(self, *, forms, **kwargs):
        context = super().get_context_data(**kwargs)

        form_user_address = forms.get("user_address")
        form_personal_data = forms.get("personal_data")
        form_birth_place = forms.get("birth_place")

        context["form_user_address"] = form_user_address
        context["form_personal_data"] = form_personal_data
        context["form_birth_place"] = form_birth_place
        context["has_form_error"] = any(
            form.errors for form in [form_user_address, form_birth_place, form_personal_data] if form is not None
        )

        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["matomo_custom_title"] = "Acceptation de la candidature - Informations du candidat"
        context["job_application"] = self.job_application
        context["job_seeker"] = self.job_seeker
        context["company"] = self.company
        context["back_url"] = self.get_back_url()
        context["hire_process"] = self.job_application is None
        return context

    def get(self, request, *args, **kwargs):
        forms = self.get_forms()
        if not forms:
            return HttpResponseRedirect(self.get_success_url())
        return super().get(request, *args, forms=forms, **kwargs)

    def post(self, request, *args, **kwargs):
        forms = self.get_forms()
        if not all([form.is_valid() for form in forms.values()]):
            context = self.get_context_data(forms=forms, **kwargs)
            return self.render_to_response(context)

        session = self.get_session()
        form_data = {form_name: form.cleaned_data for form_name, form in forms.items()}
        session.set("job_seeker_info_forms_data", form_data)

        return HttpResponseRedirect(self.get_success_url())


class BaseAcceptView(UserPassesTestMixin, CommonUserInfoFormsMixin, TemplateView):
    template_name = None

    def test_func(self):
        return self.request.user.is_employer

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.eligibility_diagnosis = None
        self.geiq_eligibility_diagnosis = None

    def get_forms(self):
        forms = super().get_forms()

        # Make the other forms appear as bound with initial data to trigger validation
        for form in forms.values():
            form.is_bound = True
            form.data = form.initial

        forms["accept"] = AcceptForm(
            instance=self.job_application,
            company=self.company,
            job_seeker=self.job_seeker,
            data=self.request.POST or None,
        )

        return forms

    def get_back_url(self):
        raise NotImplementedError

    def get_error_url(self):
        raise NotImplementedError

    def clean_session(self):
        pass

    def get_context_data(self, *, forms, **kwargs):
        form_accept = forms["accept"]
        context = super().get_context_data(**kwargs)
        context["form_accept"] = form_accept
        context["has_form_error"] = bool(form_accept.errors)
        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["hide_value"] = ContractType.OTHER.value
        context["matomo_custom_title"] = "Candidature acceptée"
        context["job_application"] = self.job_application
        context["job_seeker"] = self.job_seeker
        context["company"] = self.company
        context["back_url"] = self.get_back_url()
        context["hire_process"] = self.job_application is None
        return context

    def get_template_names(self):
        if self.request.htmx:
            return "apply/includes/job_application_accept_form.html"
        return super().get_template_names()

    def missing_or_invalid_job_seeker_infos(self, forms):
        other_forms = {k: v for k, v in forms.items() if k != "accept"}
        return bool(other_forms and not all([form.is_valid() for form in other_forms.values()]))

    def get(self, request, *args, **kwargs):
        forms = self.get_forms()
        if self.missing_or_invalid_job_seeker_infos(forms):
            messages.error(request, "Certaines informations sont manquantes ou invalides")
            return HttpResponseRedirect(self.get_back_url())
        return super().get(request, *args, forms=forms, **kwargs)

    def post(self, request, *args, **kwargs):
        forms = self.get_forms()
        if self.missing_or_invalid_job_seeker_infos(forms):
            messages.error(request, "Certaines informations sont manquantes ou invalides")
            return HttpResponseRedirect(self.get_back_url())

        if not all([form.is_valid() for form in forms.values()]):
            context = self.get_context_data(forms=forms, **kwargs)
            return self.render_to_response(context)

        if request.htmx and not request.POST.get("confirmed"):
            return TemplateResponse(
                request=request,
                template="apply/includes/job_application_accept_form.html",
                context=self.get_context_data(
                    forms=forms,
                ),
                headers=hx_trigger_modal_control("js-confirmation-modal", "show"),
            )

        creating = self.job_application is None

        try:
            with transaction.atomic():
                if form_personal_data := forms.get("personal_data"):
                    form_personal_data.save()
                    if self.eligibility_diagnosis:
                        self.eligibility_diagnosis.schedule_certification()
                if form_user_address := forms.get("user_address"):
                    form_user_address.save()
                if form_birth_place := forms.get("birth_place"):
                    form_birth_place.save()
                    if self.geiq_eligibility_diagnosis:
                        self.geiq_eligibility_diagnosis.schedule_certification()
                # Instance will be committed by the transition, performed by django-xworkflows.
                job_application = forms["accept"].save(commit=False)
                if creating:
                    job_application.job_seeker = self.job_seeker
                    job_application.to_company = self.company
                    job_application.sender = request.user
                    job_application.sender_kind = UserKind.EMPLOYER
                    job_application.sender_company = self.company
                    job_application.process(user=request.user)
                    self.job_application = job_application  # store in class to have access later
                job_application.accept(user=request.user)

                # Mark job seeker's infos as up-to-date
                job_application.job_seeker.last_checked_at = timezone.now()
                job_application.job_seeker.save(update_fields=["last_checked_at"])
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.", extra_tags="toast")
            return HttpResponseClientRedirect(self.get_error_url())

        if job_application.to_company.is_subject_to_iae_rules:
            # Automatic approval delivery mode.
            if job_application.approval:
                messages.success(request, "Candidature acceptée !", extra_tags="toast")
            # Manual approval delivery mode.
            else:
                external_link = get_external_link_markup(
                    url=(
                        f"{global_constants.ITOU_HELP_CENTER_URL}/articles/"
                        "14733528375185--PASS-IAE-Comment-ça-marche-/#verification-des-demandes-de-pass-iae"
                    ),
                    text="consulter notre espace documentation",
                )
                messages.success(
                    request,
                    mark_safe(
                        "Votre demande de PASS IAE est en cours de vérification auprès de nos équipes.<br>"
                        "Si vous souhaitez en savoir plus sur le processus de vérification, n’hésitez pas à "
                        f"{external_link}."
                    ),
                )
        elif self.geiq_eligibility_diagnosis:
            # If job seeker has as valid GEIQ diagnosis issued by a GEIQ or a prescriber
            # link this diagnosis to the current job application
            job_application.geiq_eligibility_diagnosis = self.geiq_eligibility_diagnosis
            job_application.save(update_fields=["geiq_eligibility_diagnosis", "updated_at"])

        self.clean_session()

        return HttpResponseClientRedirect(self.get_success_url())


class BaseGEIQEligibilityView(UserPassesTestMixin, FormView):
    template_name = None
    form_class = CheckJobSeekerGEIQEligibilityForm

    def test_func(self):
        return self.request.user.is_employer

    def dispatch(self, request, *args, **kwargs):
        if self.company.kind != CompanyKind.GEIQ:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["hx_post_url"] = self.request.get_full_path()
        return kwargs

    def get_next_url(self):
        raise NotImplementedError

    def get_back_url(self):
        raise NotImplementedError

    def get_success_url(self):
        return add_url_params(
            self.geiq_eligibility_criteria_url, {"back_url": self.get_back_url(), "next_url": self.get_next_url()}
        )

    def form_valid(self, form):
        if form.cleaned_data["choice"]:
            return super().form_valid(form)
        else:
            return render(
                self.request,
                "apply/includes/geiq/continue_without_geiq_diagnosis_form.html",
                context={
                    "next_url": self.get_next_url(),
                    "back_url": self.get_back_url(),
                    "progress": 66,
                },
            )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["progress"] = 33
        context["can_view_personal_information"] = True
        context["job_seeker"] = self.job_seeker
        context["siae"] = self.company
        context["back_url"] = self.get_back_url()
        context["next_url"] = self.get_next_url()
        context["geiq_criteria_form_url"] = self.get_success_url()
        return context


class BaseGEIQEligibilityCriteriaHtmxView(UserPassesTestMixin, FormView):
    """Dynamic GEIQ eligibility criteria form (HTMX)"""

    template_name = "apply/includes/geiq/check_geiq_eligibility_form.html"
    form_class = GEIQAdministrativeCriteriaForGEIQForm

    def test_func(self):
        return self.request.user.is_employer

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, self.company).first()
        self.next_url = get_safe_url(request, "next_url")
        self.back_url = get_safe_url(request, "back_url")
        self.allowance_amount = None

    def dispatch(self, request, *args, **kwargs):
        if self.company.kind != CompanyKind.GEIQ:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        form_kwargs = super().get_form_kwargs()
        form_kwargs["company"] = self.company
        form_kwargs["administrative_criteria"] = self.diagnosis.administrative_criteria.all() if self.diagnosis else []
        form_kwargs["form_url"] = self.request.path
        return form_kwargs

    def form_valid(self, form):
        criteria = form.cleaned_data
        if self.request.htmx:
            self.allowance_amount = geiq_allowance_amount(self.request.from_authorized_prescriber, criteria)
            return self.render_to_response(self.get_context_data(form=form))

        if self.diagnosis:
            GEIQEligibilityDiagnosis.update_eligibility_diagnosis(self.diagnosis, self.request.user, criteria)
        else:
            GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
                self.job_seeker, self.request.user, self.company, criteria
            )
        return HttpResponseRedirect(self.next_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["allowance_amount"] = self.allowance_amount
        context["progress"] = 66
        context["back_url"] = self.back_url

        geo_criteria_detected = self.job_seeker.address_in_qpv or self.job_seeker.zrr_city_name
        context["geo_criteria_detected"] = geo_criteria_detected
        if geo_criteria_detected:
            context["job_seeker"] = self.job_seeker
        return context
