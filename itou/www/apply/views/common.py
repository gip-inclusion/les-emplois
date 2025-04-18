from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django_htmx.http import HttpResponseClientRedirect
from django_xworkflows import models as xwf_models

from itou.asp.forms import BirthPlaceWithoutBirthdateModelForm
from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.companies.enums import CompanyKind, ContractType
from itou.eligibility.models import EligibilityDiagnosis
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
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForGEIQForm


def _accept(request, company, job_seeker, error_url, back_url, template_name, extra_context, job_application=None):
    forms = []

    # Ask the SIAE to verify the job seeker's Pôle emploi status.
    # This will ensure a smooth Approval delivery.
    form_personal_data = None
    form_user_address = None
    form_birth_place = None
    creating = job_application is None
    valid_diagnosis = None

    if company.is_subject_to_eligibility_rules:
        valid_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker, for_siae=company)
        # Info that will be used to search for an existing Pôle emploi approval.
        form_personal_data = JobSeekerPersonalDataForm(
            instance=job_seeker,
            data=request.POST or None,
            tally_form_query=f"jobapplication={job_application.pk}" if job_application else None,
        )
        forms.append(form_personal_data)
        form_user_address = JobSeekerAddressForm(instance=job_seeker, data=request.POST or None)
        forms.append(form_user_address)
    elif company.kind == CompanyKind.GEIQ:
        valid_diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(
            job_seeker=job_seeker, for_geiq=company
        ).first()
        if valid_diagnosis and valid_diagnosis.criteria_can_be_certified():
            form_birth_place = BirthPlaceWithoutBirthdateModelForm(
                instance=job_seeker.jobseeker_profile,
                birthdate=job_seeker.jobseeker_profile.birthdate,
                data=request.POST or None,
            )
            forms.append(form_birth_place)

    form_accept = AcceptForm(
        instance=job_application, company=company, job_seeker=job_seeker, data=request.POST or None
    )
    forms.append(form_accept)

    context = {
        "form_accept": form_accept,
        "form_user_address": form_user_address,
        "form_personal_data": form_personal_data,
        "form_birth_place": form_birth_place,
        "has_form_error": any(form.errors for form in forms),
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "hide_value": ContractType.OTHER.value,
        "matomo_custom_title": "Candidature acceptée",
        "job_application": job_application,
        "job_seeker": job_seeker,
        "company": company,
        "back_url": back_url,
        "hire_process": job_application is None,
    } | extra_context

    if request.method == "POST" and all([form.is_valid() for form in forms]):
        if request.htmx and not request.POST.get("confirmed"):
            return TemplateResponse(
                request=request,
                template="apply/includes/job_application_accept_form.html",
                context=context,
                headers=hx_trigger_modal_control("js-confirmation-modal", "show"),
            )

        try:
            with transaction.atomic():
                if form_personal_data:
                    form_personal_data.save()
                    if (
                        valid_diagnosis
                        and valid_diagnosis.criteria_can_be_certified()
                        and settings.API_PARTICULIER_TOKEN
                    ):
                        valid_diagnosis.certify_criteria()
                if form_user_address:
                    form_user_address.save()
                if form_birth_place:
                    form_birth_place.save()
                    if settings.API_PARTICULIER_TOKEN:
                        valid_diagnosis.certify_criteria()
                # Instance will be committed by the transition, performed by django-xworkflows.
                job_application = form_accept.save(commit=False)
                if creating:
                    job_application.job_seeker = job_seeker
                    job_application.to_company = company
                    job_application.sender = request.user
                    job_application.sender_kind = UserKind.EMPLOYER
                    job_application.sender_company = company
                    job_application.process(user=request.user)
                job_application.accept(user=request.user)

                # Mark job seeker's infos as up-to-date
                job_application.job_seeker.last_checked_at = timezone.now()
                job_application.job_seeker.save(update_fields=["last_checked_at"])
        except xwf_models.InvalidTransitionError:
            messages.error(request, "Action déjà effectuée.")
            return HttpResponseClientRedirect(error_url)

        if job_application.to_company.is_subject_to_eligibility_rules:
            # Automatic approval delivery mode.
            if job_application.approval:
                messages.success(request, "Candidature acceptée !", extra_tags="toast")
            # Manual approval delivery mode.
            elif not job_application.hiring_without_approval:
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
        elif job_application.to_company.kind == CompanyKind.GEIQ:
            # If job seeker has as valid GEIQ diagnosis issued by a GEIQ or a prescriber
            # link this diagnosis to the current job application
            if valid_diagnosis:
                job_application.geiq_eligibility_diagnosis = valid_diagnosis
                job_application.save(update_fields=["geiq_eligibility_diagnosis", "updated_at"])

        if creating and company.is_subject_to_eligibility_rules and job_application.approval:
            final_url = reverse("employees:detail", kwargs={"public_id": job_seeker.public_id})
        else:
            final_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})

        return HttpResponseClientRedirect(final_url)

    if request.htmx:
        template_name = "apply/includes/job_application_accept_form.html"

    return render(request, template_name, {**context, "has_form_error": any(form.errors for form in forms)})


def _eligibility(request, siae, job_seeker, cancel_url, next_url, template_name, extra_context):
    if not siae.is_subject_to_eligibility_rules:
        raise Http404()

    if suspension_explanation := siae.get_active_suspension_text_with_dates():
        raise PermissionDenied(
            "Vous ne pouvez pas valider les critères d'éligibilité suite aux mesures prises dans le cadre "
            "du contrôle a posteriori. " + suspension_explanation
        )

    form_administrative_criteria = AdministrativeCriteriaForm(
        request.from_authorized_prescriber, siae=siae, data=request.POST or None
    )
    if request.method == "POST" and form_administrative_criteria.is_valid():
        EligibilityDiagnosis.create_diagnosis(
            job_seeker,
            author=request.user,
            author_organization=request.current_organization,
            administrative_criteria=form_administrative_criteria.cleaned_data,
        )
        messages.success(request, "Éligibilité confirmée !", extra_tags="toast")
        return HttpResponseRedirect(next_url)

    context = {
        "can_view_personal_information": True,  # SIAE members have access to personal info
        "form_administrative_criteria": form_administrative_criteria,
        "job_seeker": job_seeker,
        "cancel_url": cancel_url,
        "matomo_custom_title": "Evaluation de la candidature",
    } | extra_context
    return render(request, template_name, context)


def _geiq_eligibility(
    request, company, job_seeker, back_url, next_url, geiq_eligibility_criteria_url, template_name, extra_context
):
    # Check GEIQ eligibility during job application process
    # Pass get_full_path to keep back/next_url query params
    form = CheckJobSeekerGEIQEligibilityForm(hx_post_url=request.get_full_path(), data=request.POST or None)
    geiq_criteria_form_url = add_url_params(
        geiq_eligibility_criteria_url,
        {
            "back_url": back_url,
            "next_url": next_url,
        },
    )

    if request.method == "POST" and form.is_valid() and request.htmx:
        if form.cleaned_data["choice"]:
            return HttpResponseRedirect(geiq_criteria_form_url)
        else:
            return render(
                request,
                "apply/includes/geiq/continue_without_geiq_diagnosis_form.html",
                context={
                    "next_url": next_url,
                    "progress": 66,
                },
            )

    context = {
        "progress": 33,
        "can_view_personal_information": True,
        "job_seeker": job_seeker,
        "siae": company,
        "form": form,
        "back_url": back_url,
        "next_url": next_url,
        "geiq_criteria_form_url": geiq_criteria_form_url,
    } | extra_context

    return render(request, template_name, context)


# HTMX fragments


def _geiq_eligibility_criteria(
    request, company, job_seeker, template_name="apply/includes/geiq/check_geiq_eligibility_form.html"
):
    """Dynamic GEIQ eligibility criteria form (HTMX)"""

    diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, company).first()
    form = GEIQAdministrativeCriteriaForGEIQForm(
        company,
        diagnosis.administrative_criteria.all() if diagnosis else [],
        request.path,
        data=request.POST or None,
    )
    next_url = get_safe_url(request, "next_url")
    allowance_amount = None

    if request.method == "POST" and form.is_valid():
        criteria = form.cleaned_data
        if request.htmx:
            allowance_amount = geiq_allowance_amount(request.from_authorized_prescriber, criteria)
        else:
            if diagnosis:
                GEIQEligibilityDiagnosis.update_eligibility_diagnosis(diagnosis, request.user, criteria)
            else:
                GEIQEligibilityDiagnosis.create_eligibility_diagnosis(job_seeker, request.user, company, criteria)

            return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "allowance_amount": allowance_amount,
        "progress": 66,
        "back_url": reverse(
            "job_seekers_views:check_job_seeker_info_for_hire",
            kwargs={"job_seeker_public_id": job_seeker.public_id, "company_pk": company.pk},
        ),
    }

    geo_criteria_detected = job_seeker.address_in_qpv or job_seeker.zrr_city_name
    context["geo_criteria_detected"] = geo_criteria_detected
    if geo_criteria_detected:
        context["job_seeker"] = job_seeker

    return render(request, template_name, context)
