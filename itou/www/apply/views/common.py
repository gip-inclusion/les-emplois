from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render

from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.utils import geiq_allowance_amount
from itou.utils.perms.user import get_user_info
from itou.utils.urls import add_url_params
from itou.www.apply.forms import CheckJobSeekerGEIQEligibilityForm
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForGEIQForm


def _eligibility(request, siae, job_seeker, cancel_url, next_url, template_name, extra_context):
    if not siae.is_subject_to_eligibility_rules:
        raise Http404()

    if suspension_explanation := siae.get_active_suspension_text_with_dates():
        raise PermissionDenied(
            "Vous ne pouvez pas valider les critères d'éligibilité suite aux mesures prises dans le cadre "
            "du contrôle a posteriori. " + suspension_explanation
        )

    form_administrative_criteria = AdministrativeCriteriaForm(request.user, siae=siae, data=request.POST or None)
    if request.method == "POST" and form_administrative_criteria.is_valid():
        user_info = get_user_info(request)
        EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=form_administrative_criteria.cleaned_data
        )
        messages.success(request, "Éligibilité confirmée !")
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
    request, siae, job_seeker, back_url, next_url, geiq_eligibility_criteria_url, template_name, extra_context
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
        "siae": siae,
        "form": form,
        "back_url": back_url,
        "next_url": next_url,
        "geiq_criteria_form_url": geiq_criteria_form_url,
    } | extra_context

    return render(request, template_name, context)


# HTMX fragments


def _geiq_eligibility_criteria(
    request, siae, job_seeker, template_name="apply/includes/geiq/check_geiq_eligibility_form.html"
):
    """Dynamic GEIQ eligibility criteria form (HTMX)"""

    diagnosis = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker, siae).first()
    form = GEIQAdministrativeCriteriaForGEIQForm(
        siae,
        diagnosis.administrative_criteria.all() if diagnosis else [],
        request.path,
        data=request.POST or None,
    )
    next_url = request.GET.get("next_url")
    allowance_amount = None

    if request.method == "POST" and form.is_valid():
        criteria = form.cleaned_data
        if request.htmx:
            allowance_amount = geiq_allowance_amount(request.user.is_prescriber_with_authorized_org, criteria)
        else:
            if diagnosis:
                GEIQEligibilityDiagnosis.update_eligibility_diagnosis(diagnosis, request.user, criteria)
            else:
                GEIQEligibilityDiagnosis.create_eligibility_diagnosis(job_seeker, request.user, siae, criteria)

            return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "allowance_amount": allowance_amount,
        "progress": 66,
    }

    if job_seeker.address_in_qpv or job_seeker.zrr_city_name:
        context |= {"geo_criteria_detected": True, "job_seeker": job_seeker}

    return render(request, template_name, context)
