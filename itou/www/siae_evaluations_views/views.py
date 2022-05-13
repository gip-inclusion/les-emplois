from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Min
from django.http import HttpResponseRedirect
from django.shortcuts import get_list_or_404, get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import (
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
)
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
from itou.www.eligibility_views.forms import AdministrativeCriteriaOfJobApplicationForm
from itou.www.siae_evaluations_views.forms import SetChosenPercentForm, SubmitEvaluatedAdministrativeCriteriaProofForm


@login_required
def samples_selection(request, template_name="siae_evaluations/samples_selection.html"):
    institution = get_current_institution_or_404(request)
    evaluation_campaign = EvaluationCampaign.objects.first_active_campaign(institution)

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    form = SetChosenPercentForm(instance=evaluation_campaign, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.instance.percent_set_at = timezone.now()
        form.save()
        messages.success(
            request,
            f"Le pourcentage de sélection pour le contrôle a posteriori "
            f"a bien été enregistré ({form.cleaned_data['chosen_percent']}%).",
        )
        return HttpResponseRedirect(back_url)

    context = {
        "institution": institution,
        "evaluation_campaign": evaluation_campaign,
        "min": evaluation_enums.EvaluationChosenPercent.MIN,
        "max": evaluation_enums.EvaluationChosenPercent.MAX,
        "back_url": back_url,
        "form": form,
    }
    return render(request, template_name, context)


@login_required
def institution_evaluated_siae_list(
    request, evaluation_campaign_pk, template_name="siae_evaluations/institution_evaluated_siae_list.html"
):
    institution = get_current_institution_or_404(request)
    evaluated_siaes = get_list_or_404(
        EvaluatedSiae,
        evaluation_campaign__pk=evaluation_campaign_pk,
        evaluation_campaign__institution=institution,
        evaluation_campaign__ended_at=None,
        evaluation_campaign__evaluations_asked_at__isnull=False,
    )
    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    context = {
        "evaluated_siaes": evaluated_siaes,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_job_applications_list(request, template_name="siae_evaluations/siae_job_applications_list.html"):

    siae = get_current_siae_or_404(request)

    evaluated_job_applications = (
        EvaluatedJobApplication.objects.exclude(evaluated_siae__evaluation_campaign__evaluations_asked_at=None)
        .filter(evaluated_siae__siae=siae, evaluated_siae__evaluation_campaign__ended_at=None)
        .select_related("job_application", "job_application__job_seeker", "job_application__approval")
        .prefetch_related("evaluated_administrative_criteria")
    )

    if evaluated_job_applications:
        is_submittable = all(
            evaluated_job_application.state == evaluation_enums.EvaluatedJobApplicationsState.UPLOADED
            for evaluated_job_application in evaluated_job_applications
        )
    else:
        is_submittable = False

    evaluations_asked_at = evaluated_job_applications.aggregate(
        date=Min("evaluated_siae__evaluation_campaign__evaluations_asked_at")
    ).get("date")

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    context = {
        "evaluated_job_applications": evaluated_job_applications,
        "evaluations_asked_at": evaluations_asked_at,
        "is_submittable": is_submittable,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_select_criteria(
    request, evaluated_job_application_pk, template_name="siae_evaluations/siae_select_criteria.html"
):
    siae = get_current_siae_or_404(request)
    evaluated_job_application = get_object_or_404(
        EvaluatedJobApplication, pk=evaluated_job_application_pk, evaluated_siae__siae=siae
    )
    initial_data = {
        eval_criterion.administrative_criteria.key: True
        for eval_criterion in evaluated_job_application.evaluated_administrative_criteria.all()
    }

    form_administrative_criteria = AdministrativeCriteriaOfJobApplicationForm(
        request.user,
        siae=siae,
        job_application=evaluated_job_application.job_application,
        data=request.POST or None,
        initial=initial_data,
    )

    url = reverse("siae_evaluations_views:siae_job_applications_list") + f"#{evaluated_job_application.pk}"

    if request.method == "POST" and form_administrative_criteria.is_valid():
        evaluated_job_application.save_selected_criteria(
            cleaned_keys=[
                administrative_criteria.key for administrative_criteria in form_administrative_criteria.cleaned_data
            ],
            changed_keys=form_administrative_criteria.changed_data,
        )

        next_url = url
        return HttpResponseRedirect(next_url)

    level_1_fields = [
        field
        for field in form_administrative_criteria
        if AdministrativeCriteriaOfJobApplicationForm.LEVEL_1_PREFIX in field.name
    ]
    level_2_fields = [
        field
        for field in form_administrative_criteria
        if AdministrativeCriteriaOfJobApplicationForm.LEVEL_2_PREFIX in field.name
    ]

    back_url = get_safe_url(request, "back_url", fallback_url=url)

    context = {
        "job_seeker": evaluated_job_application.job_application.job_seeker,
        "approval": evaluated_job_application.job_application.approval,
        "state": evaluated_job_application.state,
        "form_administrative_criteria": form_administrative_criteria,
        "level_1_fields": level_1_fields,
        "level_2_fields": level_2_fields,
        "kind": siae.kind,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_upload_doc(
    request, evaluated_administrative_criteria_pk, template_name="siae_evaluations/siae_upload_doc.html"
):

    evaluated_administrative_criteria = get_object_or_404(
        EvaluatedAdministrativeCriteria,
        pk=evaluated_administrative_criteria_pk,
        evaluated_job_application__evaluated_siae__siae=get_current_siae_or_404(request),
    )

    form = SubmitEvaluatedAdministrativeCriteriaProofForm(
        instance=evaluated_administrative_criteria, data=request.POST or None
    )

    url = (
        reverse("siae_evaluations_views:siae_job_applications_list")
        + f"#{evaluated_administrative_criteria.evaluated_job_application.pk}"
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(url)

    s3_upload = S3Upload(kind="evaluations")

    back_url = get_safe_url(request, "back_url", fallback_url=url)

    context = {
        "job_seeker": evaluated_administrative_criteria.evaluated_job_application.job_application.job_seeker,
        "approval": evaluated_administrative_criteria.evaluated_job_application.job_application.approval,
        "state": evaluated_administrative_criteria.evaluated_job_application.state,
        "evaluated_administrative_criteria": evaluated_administrative_criteria,
        "s3_form_values": s3_upload.form_values,
        "s3_upload_config": s3_upload.config,
        "form": form,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_submit_proofs(request):
    # notice this is a blind view, without template.

    siae = get_current_siae_or_404(request)

    # info : this queryset is used to check that each EvaluatedJobApplication
    # is linked to at least one EvaluatedAdministrativeCriteria, to prevent
    # submitting orphan EvaluatedJobApplication
    evaluated_job_applications = (
        EvaluatedJobApplication.objects.exclude(
            evaluated_siae__evaluation_campaign__evaluations_asked_at=None,
        )
        .filter(
            evaluated_siae__siae=siae,
            evaluated_siae__evaluation_campaign__ended_at=None,
        )
        .select_related(
            "evaluated_siae",
            "evaluated_siae__evaluation_campaign",
        )
        .prefetch_related("evaluated_administrative_criteria")
    )

    if all(
        evaluated_job_application.state == evaluation_enums.EvaluatedJobApplicationsState.UPLOADED
        for evaluated_job_application in evaluated_job_applications
    ):

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__in=evaluated_job_applications
        ).update(submitted_at=timezone.now())

        back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
        messages.success(
            request,
            mark_safe(
                "<b>Justificatifs transmis !</b><br>"
                "Merci d'avoir pris le temps de transmettre vos pièces justificatives.<br>"
                "Le contrôle de celles-ci est à la charge de votre DDETS maintenant, vous serez notifié du résultat "
                "(qu'il soit positif ou négatif) par mail lorsque celui-ci sera finalisé."
            ),
        )
        return HttpResponseRedirect(back_url)

    return HttpResponseRedirect(reverse("siae_evaluations_views:siae_job_applications_list"))
