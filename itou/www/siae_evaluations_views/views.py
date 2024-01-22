from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_list_or_404, get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views import generic
from django.views.decorators.http import require_POST, require_safe
from django.views.generic.detail import SingleObjectMixin

from itou.files.models import File
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.emails import InstitutionEmailFactory, SIAEEmailFactory
from itou.siae_evaluations.models import (
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
    Sanctions,
)
from itou.utils.emails import send_email_messages
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.urls import get_safe_url
from itou.www.eligibility_views.forms import AdministrativeCriteriaOfJobApplicationForm
from itou.www.siae_evaluations_views.forms import (
    InstitutionEvaluatedSiaeNotifyStep1Form,
    InstitutionEvaluatedSiaeNotifyStep2Form,
    InstitutionEvaluatedSiaeNotifyStep3Form,
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
        "matomo_custom_title": "Contrôle a posteriori : sélectionner l'échantillon",
    }
    return render(request, template_name, context)


@login_required
def campaign_calendar(request, evaluation_campaign_pk, template_name="siae_evaluations/campaign_calendar.html"):
    evaluation_campaign = get_object_or_404(
        EvaluationCampaign,
        pk=evaluation_campaign_pk,
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    if request.user.is_employer:
        evaluated_siae = get_object_or_404(
            EvaluatedSiae,
            evaluation_campaign=evaluation_campaign,
            siae=request.current_organization,
        )
        evaluation_url = reverse("siae_evaluations_views:siae_job_applications_list", args=[evaluated_siae.pk])
    else:
        evaluation_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list", args=[evaluation_campaign.pk]
        )
    breadcrumbs = {
        "Contrôle a posteriori": evaluation_url,
        "Calendrier": request.path,
    }
    context = {
        "breadcrumbs": breadcrumbs,
        "campaign_calendar_html": evaluation_campaign.calendar.html,
        "back_url": back_url,
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
        "accepted_by_default": (
            evaluated_siae.final_reviewed_at
            and evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED
            and any(
                evaluated_jobapp.compute_state() != evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED
                for evaluated_jobapp in evaluated_siae.evaluated_job_applications.all()
            )
        ),
    }
    return render(request, template_name, context)


def evaluation_campaign_data_context(evaluated_siae):
    context = {}
    job_apps = evaluated_siae.evaluated_job_applications.all()
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
        .filter(siae=evaluated_siae.siae_id)
        .exclude(pk=evaluated_siae.pk)
        .order_by("-evaluation_campaign__evaluated_period_start_at")
        .select_related("evaluation_campaign", "sanctions")
        .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
    )
    return context


class InstitutionEvaluatedSiaeNotifyMixin(LoginRequiredMixin, SingleObjectMixin):
    model = EvaluatedSiae
    context_object_name = "evaluated_siae"
    pk_url_kwarg = "evaluated_siae_pk"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if request.user.is_authenticated:
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
        context.update(evaluation_campaign_data_context(self.object))
        context["matomo_custom_title"] = "Notifier la sanction du contrôle"
        return context

    @property
    def sessionkey(self):
        return f"siae_evaluations_views:institution_evaluated_siae_notify-{self.kwargs['evaluated_siae_pk']}"


class InstitutionEvaluatedSiaeNotifyStep1View(InstitutionEvaluatedSiaeNotifyMixin, generic.UpdateView):
    form_class = InstitutionEvaluatedSiaeNotifyStep1Form
    template_name = "siae_evaluations/institution_evaluated_siae_notify_step1.html"

    def get_success_url(self):
        return reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify_step2",
            kwargs={"evaluated_siae_pk": self.object.pk},
        )


class InstitutionEvaluatedSiaeNotifyStep2View(InstitutionEvaluatedSiaeNotifyMixin, generic.FormView):
    form_class = InstitutionEvaluatedSiaeNotifyStep2Form
    template_name = "siae_evaluations/institution_evaluated_siae_notify_step2.html"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial["sanctions"] = self.request.session.get(self.sessionkey, {}).get("sanctions")
        return initial

    def form_valid(self, form):
        self.request.session[self.sessionkey] = {"sanctions": form.cleaned_data["sanctions"]}
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify_step3",
            kwargs={"evaluated_siae_pk": self.object.pk},
        )


class InstitutionEvaluatedSiaeNotifyStep3View(InstitutionEvaluatedSiaeNotifyMixin, generic.FormView):
    form_class = InstitutionEvaluatedSiaeNotifyStep3Form
    template_name = "siae_evaluations/institution_evaluated_siae_notify_step3.html"

    def get(self, request, *args, **kwargs):
        if self.sessionkey not in request.session:
            return HttpResponseRedirect(
                reverse(
                    "siae_evaluations_views:institution_evaluated_siae_notify_step2",
                    kwargs={"evaluated_siae_pk": self.kwargs["evaluated_siae_pk"]},
                )
            )
        self.object = self.get_object()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.sessionkey not in request.session:
            return HttpResponseRedirect(
                reverse(
                    "siae_evaluations_views:institution_evaluated_siae_notify_step2",
                    kwargs={"evaluated_siae_pk": self.kwargs["evaluated_siae_pk"]},
                )
            )
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["sanctions"] = self.request.session[self.sessionkey]["sanctions"]
        return kwargs

    def form_valid(self, form):
        evaluated_siae = self.object
        sanctions = Sanctions(
            evaluated_siae=evaluated_siae,
            training_session=form.cleaned_data.get("training_session", ""),
            suspension_dates=form.cleaned_data.get("suspension_dates"),
            subsidy_cut_percent=form.cleaned_data.get("subsidy_cut_percent"),
            subsidy_cut_dates=form.cleaned_data.get("subsidy_cut_dates"),
            deactivation_reason=form.cleaned_data.get("deactivation_reason", ""),
            no_sanction_reason=form.cleaned_data.get("no_sanction_reason", ""),
        )
        evaluated_siae.notified_at = timezone.now()
        sanctions.save()
        evaluated_siae.save(update_fields=["notified_at"])
        del self.request.session[self.sessionkey]
        messages.success(self.request, f"{evaluated_siae} a bien été notifiée de la sanction.")
        if sanctions.no_sanction_reason:
            email = SIAEEmailFactory(evaluated_siae).not_sanctioned()
        else:
            email = SIAEEmailFactory(evaluated_siae).sanctioned()
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
        "siae": (get_current_company_or_404, "siae"),
    }
    viewer_or_404, filter_lookup = allowed_viewers[viewer_type]
    viewer = viewer_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.filter(
            pk=evaluated_siae_pk,
            **{filter_lookup: viewer},
        )
        .exclude(notified_at=None)
        .select_related("evaluation_campaign", "sanctions")
    )
    context = evaluation_campaign_data_context(evaluated_siae)
    context["evaluated_siae"] = evaluated_siae
    context["is_siae"] = viewer_type == "siae"
    context["matomo_custom_title"] = "Notification de sanction"
    try:
        context["sanctions"] = evaluated_siae.sanctions
    except EvaluatedSiae.sanctions.RelatedObjectDoesNotExist:
        context["sanctions"] = None
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
        evaluated_siae.review()
        messages.success(
            request,
            mark_safe(
                "<b>Résultats enregistrés !</b><br>"
                "Merci d'avoir pris le temps de contrôler les pièces justificatives."
            ),
        )

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
    siae = get_current_company_or_404(request)
    evaluated_siae = get_object_or_404(
        EvaluatedSiae.objects.filter(pk=evaluated_siae_pk, siae=siae, evaluation_campaign__ended_at=None)
        .exclude(evaluation_campaign__evaluations_asked_at=None)
        .select_related("evaluation_campaign")
        .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
    )

    evaluated_job_applications = (
        EvaluatedJobApplication.objects.filter(evaluated_siae=evaluated_siae)
        .select_related(
            "evaluated_siae__evaluation_campaign__calendar",
            "job_application",
            "job_application__job_seeker",
            "job_application__approval",
        )
        .prefetch_related("evaluated_administrative_criteria")
    )

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    context = {
        "evaluated_siae": evaluated_siae,
        "evaluated_job_applications": evaluated_job_applications,
        "is_submittable": evaluated_siae.can_submit,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def siae_select_criteria(
    request, evaluated_job_application_pk, template_name="siae_evaluations/siae_select_criteria.html"
):
    siae = get_current_company_or_404(request)
    evaluated_job_application = get_object_or_404(
        EvaluatedJobApplication,
        pk=evaluated_job_application_pk,
        evaluated_siae__siae=siae,
        evaluated_siae__evaluation_campaign__ended_at__isnull=True,
    )
    if (
        evaluated_job_application.should_select_criteria
        == evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE
    ):
        return HttpResponseForbidden()
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
        "state": evaluated_job_application.compute_state(),
        "form_administrative_criteria": form_administrative_criteria,
        "level_1_fields": level_1_fields,
        "level_2_fields": level_2_fields,
        "kind": siae.kind,
        "back_url": back_url,
        "matomo_custom_title": "Contrôle a posteriori : sélection des critères",
    }
    return render(request, template_name, context)


@login_required
def siae_upload_doc(
    request, evaluated_administrative_criteria_pk, template_name="siae_evaluations/siae_upload_doc.html"
):
    evaluated_administrative_criteria = get_object_or_404(
        EvaluatedAdministrativeCriteria.objects.select_related("evaluated_job_application"),
        pk=evaluated_administrative_criteria_pk,
        evaluated_job_application__evaluated_siae__siae=get_current_company_or_404(request),
        evaluated_job_application__evaluated_siae__evaluation_campaign__ended_at__isnull=True,
    )

    if not evaluated_administrative_criteria.can_upload():
        return HttpResponseForbidden()

    form = SubmitEvaluatedAdministrativeCriteriaProofForm(data=request.POST or None, files=request.FILES or None)

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
        proof_file = form.cleaned_data["proof"]
        proof_key = default_storage.save(f"evaluations/{proof_file.name}", proof_file)
        evaluated_administrative_criteria.proof = File.objects.create(key=proof_key)
        evaluated_administrative_criteria.uploaded_at = timezone.now()
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.submitted_at = None
        evaluated_administrative_criteria.save(update_fields=["proof", "uploaded_at", "review_state", "submitted_at"])
        return HttpResponseRedirect(url)

    back_url = get_safe_url(request, "back_url", fallback_url=url)

    context = {
        "job_seeker": evaluated_administrative_criteria.evaluated_job_application.job_application.job_seeker,
        "evaluated_administrative_criteria": evaluated_administrative_criteria,
        "form": form,
        "back_url": back_url,
        "matomo_custom_title": "Contrôle a posteriori : téléversement des justificatifs",
    }
    return render(request, template_name, context)


@login_required
@require_POST
def siae_submit_proofs(request, evaluated_siae_pk):
    evaluated_siae = get_object_or_404(
        EvaluatedSiae,
        pk=evaluated_siae_pk,
        siae=get_current_company_or_404(request),
        evaluation_campaign__evaluations_asked_at__isnull=False,
        evaluation_campaign__ended_at=None,
    )
    if not evaluated_siae.can_submit:
        # This should not happen since the form to POST here only appear if can_submit is True
        # but if someone manages to POST it, tell the user it didn't work
        messages.error(request, "Impossible de soumettre les documents.")
        return HttpResponseRedirect(
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )

    now = timezone.now()
    EvaluatedAdministrativeCriteria.objects.filter(
        evaluated_job_application__evaluated_siae=evaluated_siae,
        review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
    ).update(submitted_at=now)
    # Freeze submission until next phase (or until campaign end)
    evaluated_siae.submission_freezed_at = now
    evaluated_siae.save(update_fields=("submission_freezed_at",))

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    # note vincentporte : misconception. This view should be called with one evaluated_siae
    # check this impact when calling this view with evaluated_siae.pk in params
    send_email_messages([InstitutionEmailFactory(evaluated_siae).submitted_by_siae()])

    messages.success(
        request,
        (
            "Justificatifs transmis !||Leur contrôle est à la charge de votre DDETS."
            "Une fois finalisée, vous serez notifié du résultat par email."
        ),
        extra_tags="toast",
    )
    return HttpResponseRedirect(back_url)


@login_required
@require_safe
def view_proof(request, evaluated_administrative_criteria_id):
    if request.user.is_employer:
        org_lookup = "evaluated_job_application__evaluated_siae__siae__in"
    elif request.user.is_labor_inspector:
        org_lookup = "evaluated_job_application__evaluated_siae__evaluation_campaign__institution__in"
    else:
        raise Http404(request.user.kind)
    org_filter = {org_lookup: request.organizations}
    criteria = get_object_or_404(
        EvaluatedAdministrativeCriteria,
        pk=evaluated_administrative_criteria_id,
        proof__isnull=False,
        **org_filter,
    )
    return HttpResponseRedirect(default_storage.url(criteria.proof_id))


def sanctions_helper_view(request):
    return render(request, "siae_evaluations/sanctions_helper.html")
