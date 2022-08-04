from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import mail
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
from itou.www.siae_evaluations_views.forms import (
    LaborExplanationForm,
    SetChosenPercentForm,
    SubmitEvaluatedAdministrativeCriteriaProofForm,
)


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
        EvaluatedSiae.objects.select_related("evaluation_campaign", "siae")
        .prefetch_related(  # select related `siae`` because of __str__() method of EvaluatedSiae
            "evaluated_job_applications", "evaluated_job_applications__evaluated_administrative_criteria"
        )
        .order_by("siae__name"),
        evaluation_campaign__pk=evaluation_campaign_pk,
        evaluation_campaign__institution=institution,
        evaluation_campaign__evaluations_asked_at__isnull=False,
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    context = {
        "evaluations_asked_at": evaluated_siaes[0].evaluation_campaign.evaluations_asked_at
        if evaluated_siaes
        else None,
        "evaluated_siaes": evaluated_siaes,
        "ended_at": evaluated_siaes[0].evaluation_campaign.ended_at,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def institution_evaluated_siae_detail(
    request, evaluated_siae_pk, template_name="siae_evaluations/institution_evaluated_siae_detail.html"
):
    institution = get_current_institution_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.select_related("evaluation_campaign", "siae").prefetch_related(
            "evaluated_job_applications",
            "evaluated_job_applications__evaluated_administrative_criteria",
            "evaluated_job_applications__job_application",
            "evaluated_job_applications__job_application__approval",
            "evaluated_job_applications__job_application__job_seeker",
        ),
        pk=evaluated_siae_pk,
        evaluation_campaign__institution=institution,
        evaluation_campaign__evaluations_asked_at__isnull=False,
    )
    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign.pk},
        ),
    )
    context = {
        "evaluated_siae": evaluated_siae,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def institution_evaluated_job_application(
    request, evaluated_job_application_pk, template_name="siae_evaluations/institution_evaluated_job_application.html"
):
    institution = get_current_institution_or_404(request)
    evaluated_job_application = get_object_or_404(
        EvaluatedJobApplication.objects.prefetch_related(
            "evaluated_administrative_criteria",
            "evaluated_administrative_criteria__administrative_criteria",
            "job_application",
            "job_application__approval",
            "job_application__job_seeker",
        ).select_related("evaluated_siae"),
        pk=evaluated_job_application_pk,
        evaluated_siae__evaluation_campaign__institution=institution,
        evaluated_siae__evaluation_campaign__evaluations_asked_at__isnull=False,
    )

    back_url = (
        get_safe_url(
            request,
            "back_url",
            fallback_url=reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae.pk},
            ),
        )
        + f"#{evaluated_job_application.pk}"
    )

    form = LaborExplanationForm(instance=evaluated_job_application, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        evaluated_job_application.labor_inspector_explanation = form.cleaned_data["labor_inspector_explanation"]
        evaluated_job_application.save(update_fields=["labor_inspector_explanation"])
        return HttpResponseRedirect(back_url)

    context = {
        "evaluated_job_application": evaluated_job_application,
        # note vincentporte: Can't find why additionnal queries are made to access `EvaluatedSiae` `state`
        # cached_property when iterating over `EvaluatedAdministrativeCriteria` in template.
        # Tried to push `EvaluatedSiae` instance in context without benefical results. weird.
        "evaluated_siae": evaluated_job_application.evaluated_siae,
        "form": form,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def institution_evaluated_administrative_criteria(request, evaluated_administrative_criteria_pk, action):
    institution = get_current_institution_or_404(request)
    evaluated_administrative_criteria = get_object_or_404(
        EvaluatedAdministrativeCriteria,
        pk=evaluated_administrative_criteria_pk,
        evaluated_job_application__evaluated_siae__evaluation_campaign__institution=institution,
        evaluated_job_application__evaluated_siae__evaluation_campaign__evaluations_asked_at__isnull=False,
        evaluated_job_application__evaluated_siae__evaluation_campaign__ended_at__isnull=True,
    )
    if action == "reinit":
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
    elif action == "accept":
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
    elif action == "refuse" and evaluated_administrative_criteria.evaluated_job_application.evaluated_siae.reviewed_at:
        evaluated_administrative_criteria.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
    else:
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED

    evaluated_administrative_criteria.save(update_fields=["review_state"])

    return HttpResponseRedirect(
        reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            args=[evaluated_administrative_criteria.evaluated_job_application.pk],
        )
    )


@login_required
def institution_evaluated_siae_validation(request, evaluated_siae_pk):
    institution = get_current_institution_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.select_related("evaluation_campaign").prefetch_related(
            "evaluated_job_applications",
            "evaluated_job_applications__evaluated_administrative_criteria",
        ),
        pk=evaluated_siae_pk,
        evaluation_campaign__institution=institution,
        evaluation_campaign__evaluations_asked_at__isnull=False,
        evaluation_campaign__ended_at__isnull=True,
    )

    evaluated_siae.review()

    return HttpResponseRedirect(
        reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
    )


@login_required
def siae_job_applications_list(request, template_name="siae_evaluations/siae_job_applications_list.html"):

    # note vincentporte : misconception. This view should be called with one evaluated_siae
    # id, not trying to deal with any evaluated_siae of one siae. Must be fixed soon.
    siae = get_current_siae_or_404(request)
    evaluated_siae = (
        EvaluatedSiae.objects.filter(siae=siae, evaluation_campaign__ended_at=None)
        .exclude(evaluation_campaign__evaluations_asked_at=None)
        .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
        .first()
    )

    evaluated_job_applications = (
        EvaluatedJobApplication.objects.filter(evaluated_siae=evaluated_siae)
        .select_related(
            "evaluated_siae", "job_application", "job_application__job_seeker", "job_application__approval"
        )
        .prefetch_related("evaluated_administrative_criteria")
    )

    evaluations_asked_at = evaluated_job_applications.aggregate(
        date=Min("evaluated_siae__evaluation_campaign__evaluations_asked_at")
    ).get("date")

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    context = {
        "evaluated_job_applications": evaluated_job_applications,
        "evaluations_asked_at": evaluations_asked_at,
        "is_submittable": evaluated_siae and evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_select_criteria(
    request, evaluated_job_application_pk, template_name="siae_evaluations/siae_select_criteria.html"
):
    siae = get_current_siae_or_404(request)
    evaluated_job_application = get_object_or_404(
        EvaluatedJobApplication,
        pk=evaluated_job_application_pk,
        evaluated_siae__siae=siae,
        evaluated_siae__evaluation_campaign__ended_at__isnull=True,
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
        evaluated_job_application__evaluated_siae__evaluation_campaign__ended_at__isnull=True,
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

    back_url = get_safe_url(request, "back_url", fallback_url=url)

    context = {
        "evaluated_administrative_criteria": evaluated_administrative_criteria,
        "s3_upload": S3Upload(kind="evaluations"),
        "form": form,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_submit_proofs(request):
    # notice this is a blind view, without template.

    # note vincentporte : misconception. This view should be called with one evaluated_siae
    # move all this logic into model after fixing call with one evaluated_siae
    # info : this queryset is used to check that each EvaluatedJobApplication
    # is linked to at least one EvaluatedAdministrativeCriteria, to prevent
    # submitting orphan EvaluatedJobApplication
    evaluated_siae = get_object_or_404(
        EvaluatedSiae,
        siae=get_current_siae_or_404(request),
        evaluation_campaign__evaluations_asked_at__isnull=False,
        evaluation_campaign__ended_at=None,
    )

    evaluated_job_applications = EvaluatedJobApplication.objects.filter(
        evaluated_siae=evaluated_siae
    ).prefetch_related("evaluated_administrative_criteria")

    # if at least one of those job applications is uploaded but not yet transmitted, or accepted, let's submit.
    if evaluated_job_applications and any(
        (
            evaluated_job_application.state == evaluation_enums.EvaluatedJobApplicationsState.UPLOADED
            or evaluated_job_application.state == evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED
        )
        for evaluated_job_application in evaluated_job_applications
    ):
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__in=evaluated_job_applications,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
        ).update(submitted_at=timezone.now())

        back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

        # note vincentporte : misconception. This view should be called with one evaluated_siae
        # check this impact when calling this view with evaluated_siae.pk in params
        connection = mail.get_connection()
        connection.send_messages([evaluated_siae.get_email_to_institution_submitted_by_siae()])

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
