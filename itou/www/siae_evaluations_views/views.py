import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Min, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_list_or_404, get_object_or_404, render
from django.urls import reverse
from django.utils import text, timezone
from django.utils.safestring import mark_safe
from django.views import generic
from django.views.decorators.http import require_POST

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.emails import InstitutionEmailFactory, SIAEEmailFactory
from itou.siae_evaluations.models import (
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
)
from itou.utils.emails import send_email_messages
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
from itou.www.eligibility_views.forms import AdministrativeCriteriaOfJobApplicationForm
from itou.www.siae_evaluations_views.forms import (
    InstitutionEvaluatedSiaeNotifyForm,
    LaborExplanationForm,
    SetChosenPercentForm,
    SubmitEvaluatedAdministrativeCriteriaProofForm,
)


@login_required
def samples_selection(request, template_name="siae_evaluations/samples_selection.html"):
    institution = get_current_institution_or_404(request)
    evaluation_campaign = get_object_or_404(
        EvaluationCampaign.objects.for_institution(institution).in_progress(),
    )

    dashboard_url = reverse("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)

    form = SetChosenPercentForm(instance=evaluation_campaign, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["opt_out"]:
            msg = (
                f"{text.capfirst(institution)} ne participera pas à la campagne de contrôle a posteriori "
                f"{evaluation_campaign.name}."
            )
            evaluation_campaign.delete()
            messages.success(request, msg)
            return HttpResponseRedirect(dashboard_url)
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
    evaluation_campaign = get_object_or_404(
        EvaluationCampaign,
        pk=evaluation_campaign_pk,
        institution=institution,
        evaluations_asked_at__isnull=False,
    )
    evaluated_siaes = get_list_or_404(
        EvaluatedSiae.objects.viewable()
        # select related `siae`` because of __str__() method of EvaluatedSiae
        .select_related("evaluation_campaign", "siae")
        .prefetch_related(
            "evaluated_job_applications", "evaluated_job_applications__evaluated_administrative_criteria"
        )
        .order_by("siae__name"),
        evaluation_campaign=evaluation_campaign,
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    context = {
        "evaluation_campaign": evaluation_campaign,
        "evaluated_siaes": evaluated_siaes,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def institution_evaluated_siae_detail(
    request, evaluated_siae_pk, template_name="siae_evaluations/institution_evaluated_siae_detail.html"
):
    institution = get_current_institution_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.viewable()
        .select_related("evaluation_campaign", "siae")
        .prefetch_related(
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
    evaluation_campaign = evaluated_siae.evaluation_campaign
    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        ),
    )
    context = {
        "evaluated_siae": evaluated_siae,
        "back_url": back_url,
        "campaign_closed_before_final_evaluation": (
            evaluation_campaign.ended_at and not evaluated_siae.final_reviewed_at
        ),
        "show_notified": (
            not evaluation_campaign.ended_at
            and evaluated_siae.reviewed_at
            and (
                evaluated_siae.final_reviewed_at
                and evaluated_siae.state
                in {
                    evaluation_enums.EvaluatedSiaeState.ACCEPTED,
                    evaluation_enums.EvaluatedSiaeState.REFUSED,
                }
                or evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE
                # Hide the “Résultats transmis !” banner when SIAE starts
                # uploading new documents. Otherwise, the banner is shown while
                # the SIAE remains in ADVERSARIAL_STAGE (until the institution
                # submits their second review), and the page would not look
                # much different after the second review is submitted.
                and not EvaluatedAdministrativeCriteria.objects.filter(
                    evaluated_job_application__evaluated_siae_id=evaluated_siae.pk,
                    submitted_at__gt=evaluated_siae.reviewed_at,
                ).exists()
            )
        ),
    }
    return render(request, template_name, context)


class InstitutionEvaluatedSiaeNotifyView(LoginRequiredMixin, generic.UpdateView):
    model = EvaluatedSiae
    form_class = InstitutionEvaluatedSiaeNotifyForm
    template_name = "siae_evaluations/institution_evaluated_siae_notify.html"
    context_object_name = "evaluated_siae"
    pk_url_kwarg = "evaluated_siae_pk"

    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        self.institution = get_current_institution_or_404(self.request)

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .viewable()
            .filter(
                Q(evaluation_campaign__ended_at__isnull=False) | Q(final_reviewed_at__isnull=False),
                pk=self.kwargs["evaluated_siae_pk"],
                evaluation_campaign__institution=self.institution,
                notified_at=None,
            )
            .select_related("evaluation_campaign", "siae")
            .prefetch_related(
                "evaluated_job_applications__evaluated_administrative_criteria",
                "evaluated_job_applications__job_application__eligibility_diagnosis__administrative_criteria",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job_apps = self.object.evaluated_job_applications.all()
        job_apps_count = len(job_apps)
        crits_count = 0
        crits_not_submitted = 0
        expected_crits_count = 0
        crits_refused = 0
        for evaluated_jobapp in job_apps:
            evaluated_administrative_criteria = evaluated_jobapp.evaluated_administrative_criteria.all()
            if evaluated_administrative_criteria:
                # User selected administrative criteria they will prove.
                for crit in evaluated_administrative_criteria:
                    crits_count += 1
                    if crit.submitted_at is None:
                        crits_not_submitted += 1
                        expected_crits_count += 1
                    elif crit.review_state in [
                        evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
                        evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
                    ]:
                        crits_refused += 1
            else:
                guessed_crits_count = len(
                    evaluated_jobapp.job_application.eligibility_diagnosis.administrative_criteria.all()
                )
                expected_crits_count += guessed_crits_count
                crits_count += guessed_crits_count
        context["uploaded_count"] = crits_not_submitted
        context["not_submitted_percent"] = expected_crits_count / crits_count * 100.0 if crits_count else 0.0
        context["expected_crits_count"] = expected_crits_count
        context["refused_percent"] = crits_refused / crits_count * 100.0 if crits_count else 0.0
        context["job_apps_count"] = job_apps_count
        context["evaluation_history"] = (
            EvaluatedSiae.objects.viewable()
            .filter(siae=self.object.siae_id)
            .exclude(pk=self.object.pk)
            # Ignore first evaluation campaigns, they were a test.
            .exclude(evaluation_campaign__evaluated_period_end_at__lt=datetime.date(2022, 1, 1))
            .order_by("-evaluation_campaign__evaluated_period_start_at")
            .select_related("evaluation_campaign")
            .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
        )
        return context

    def form_valid(self, form):
        messages.success(self.request, f"{self.object} a bien été notifiée de la sanction.")
        email = SIAEEmailFactory(self.object).sanctioned()
        send_email_messages([email])
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": self.object.evaluation_campaign_id},
        )


@login_required
def evaluated_siae_sanction(request, evaluated_siae_pk, viewer_type):
    allowed_viewers = {
        "institution": (get_current_institution_or_404, "evaluation_campaign__institution"),
        "siae": (get_current_siae_or_404, "siae"),
    }
    viewer_or_404, filter_lookup = allowed_viewers[viewer_type]
    viewer = viewer_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.filter(
            pk=evaluated_siae_pk,
            **{filter_lookup: viewer},
        )
        .exclude(notified_at=None)
        .select_related("evaluation_campaign")
    )
    context = {"evaluated_siae": evaluated_siae}
    return render(request, "siae_evaluations/evaluated_siae_sanction.html", context)


@login_required
def institution_evaluated_job_application(
    request, evaluated_job_application_pk, template_name="siae_evaluations/institution_evaluated_job_application.html"
):
    institution = get_current_institution_or_404(request)
    evaluated_job_application = get_object_or_404(
        EvaluatedJobApplication.objects.viewable()
        .prefetch_related(
            "evaluated_administrative_criteria",
            "evaluated_administrative_criteria__administrative_criteria",
            "job_application",
            "job_application__approval",
            "job_application__job_seeker",
        )
        .select_related("evaluated_siae__evaluation_campaign"),
        pk=evaluated_job_application_pk,
        evaluated_siae__evaluation_campaign__institution=institution,
        evaluated_siae__evaluation_campaign__evaluations_asked_at__isnull=False,
    )
    evaluated_siae = evaluated_job_application.evaluated_siae

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
    if request.method == "POST":
        if evaluated_job_application.evaluated_siae.evaluation_is_final:
            raise Http404
        if form.is_valid():
            evaluated_job_application.labor_inspector_explanation = form.cleaned_data["labor_inspector_explanation"]
            evaluated_job_application.save(update_fields=["labor_inspector_explanation"])
            return HttpResponseRedirect(back_url)

    if not evaluated_siae.reviewed_at:
        # “Phase amiable”.
        review_in_progress = any(
            eval_admin_crit.submitted_at
            for eval_admin_crit in evaluated_job_application.evaluated_administrative_criteria.all()
        )
    else:
        review_in_progress = (
            # “Phase contradictoire”.
            not evaluated_siae.final_reviewed_at
            and any(
                eval_admin_crit.submitted_at and eval_admin_crit.submitted_at > evaluated_siae.reviewed_at
                for eval_admin_crit in evaluated_job_application.evaluated_administrative_criteria.all()
            )
        )
    context = {
        "evaluated_job_application": evaluated_job_application,
        # note vincentporte: Can't find why additional queries are made to access `EvaluatedSiae` `state`
        # cached_property when iterating over `EvaluatedAdministrativeCriteria` in template.
        # Tried to push `EvaluatedSiae` instance in context without benefical results. weird.
        "evaluated_siae": evaluated_siae,
        "can_edit_proof": review_in_progress,
        "form": form,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
@require_POST
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
@require_POST
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

    if evaluated_siae.can_review:
        with transaction.atomic():
            evaluated_siae.review()

    return HttpResponseRedirect(
        reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
    )


@login_required
def siae_job_applications_list(
    request,
    evaluated_siae_pk,
    template_name="siae_evaluations/siae_job_applications_list.html",
):
    siae = get_current_siae_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.filter(pk=evaluated_siae_pk, siae=siae, evaluation_campaign__ended_at=None)
        .exclude(evaluation_campaign__evaluations_asked_at=None)
        .select_related("evaluation_campaign")
        .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
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
        "evaluated_siae": evaluated_siae,
        "evaluated_job_applications": evaluated_job_applications,
        "evaluations_asked_at": evaluations_asked_at,
        "is_submittable": evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
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

    url = (
        reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
        )
        + f"#{evaluated_job_application.pk}"
    )

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
        EvaluatedAdministrativeCriteria.objects.select_related("evaluated_job_application"),
        pk=evaluated_administrative_criteria_pk,
        evaluated_job_application__evaluated_siae__siae=get_current_siae_or_404(request),
        evaluated_job_application__evaluated_siae__evaluation_campaign__ended_at__isnull=True,
    )

    form = SubmitEvaluatedAdministrativeCriteriaProofForm(
        instance=evaluated_administrative_criteria, data=request.POST or None
    )

    url = (
        reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={
                "evaluated_siae_pk": evaluated_administrative_criteria.evaluated_job_application.evaluated_siae_id
            },
        )
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
@require_POST
def siae_submit_proofs(request, evaluated_siae_pk):
    evaluated_siae = get_object_or_404(
        EvaluatedSiae,
        pk=evaluated_siae_pk,
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
        send_email_messages([InstitutionEmailFactory(evaluated_siae).submitted_by_siae()])

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

    return HttpResponseRedirect(
        reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
    )
