import functools

from dateutil.relativedelta import relativedelta
from django import forms
from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import Approval, Suspension
from itou.approvals.perms import can_view_approval_details
from itou.approvals.utils import get_contracts
from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.companies.enums import ProSupportReportBarrier
from itou.companies.models import ProSupportReport
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.insertion.enums import OrientationRefusalReason
from itou.next_steps.models import BarrierStatus, JobSeekerBarrier, LiftCause
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.users.perms import (
    can_fill_pro_support_report,
    can_view_pro_support_report,
)
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.views import with_triggers_context
from itou.www.apply.views.process_views import job_application_sender_left_org
from itou.www.next_steps_views import engine
from itou.www.next_steps_views.access import can_view_next_steps
from itou.www.next_steps_views.actions import (
    Group,
    describe_job_seekers,
    done_today,
    expected_actions,
    group_actions,
    next_action,
)
from itou.www.next_steps_views.advisors import (
    _job_application_url,
    _job_applications,
    advisor_acts,
    visible_orientations,
)
from itou.www.next_steps_views.barriers import BARRIER_ICONS, OTHER, gather_barriers, ongoing_orientations
from itou.www.next_steps_views.coverage import contract_lines, contract_steps, coverage, period
from itou.www.next_steps_views.file import file_parts
from itou.www.next_steps_views.journeys import JOURNEYS
from itou.www.next_steps_views.period_bar import situation_bar
from itou.www.next_steps_views.situation import contract_place, situation_sentences


def _journeys_media(request):
    """Scripts of the forms the journeys may show, loaded with the page: htmx does not run swapped scripts."""
    media = forms.Media()
    if request.from_employer:
        for field in JobSeekerAddressForm.base_fields.values():
            media += field.widget.media
    return media


@readonly_view
def todo(request, template_name="next_steps/todo.html"):
    """« À faire »: the actions expected from the signed-in professional, by urgency."""
    if not can_view_next_steps(request):
        raise Http404

    actions = expected_actions(request)
    describe_job_seekers(actions, lambda job_seeker: can_view_personal_information(request, job_seeker))
    done = done_today(request)
    describe_job_seekers(done, lambda job_seeker: can_view_personal_information(request, job_seeker))
    context = {
        "groups": group_actions(actions),
        "pressing_count": sum(action.group != Group.WATCH for action in actions),
        "done_today": done,
        "journeys_media": _journeys_media(request),
        "matomo_custom_title": "Prochaines étapes : à faire",
    }
    return render(request, template_name, context)


def _can_view_contracts(request):
    # Same rule as job_seekers_views.ContractsTabView.
    return request.from_authorized_prescriber or (request.from_employer and request.from_iae_actor)


def _eligibility_summary(diagnosis, approval):
    if diagnosis is None:
        return "Aucun diagnostic en cours de validité"
    if diagnosis.is_valid:
        return f"Valide jusqu’au {diagnosis.expires_at:%d/%m/%Y}"
    # An expired diagnosis is considered valid for the duration of the PASS IAE.
    if approval and approval.is_valid:
        return f"Couvert par le PASS IAE jusqu’au {approval.end_at:%d/%m/%Y}"
    return "Aucun diagnostic en cours de validité"


def _contracts_for_situation(job_seeker, approval):
    # Same contracts as job_seekers_views.ContractsTabView.
    if approval is None or not approval.is_valid:
        two_years_ago = timezone.localdate() - relativedelta(years=2)
        contracts = job_seeker.contracts.exclude(end_date__lt=two_years_ago)
    else:
        contracts = get_contracts(approval)
    return list(contracts.select_related("company").order_by("start_date"))


@readonly_view
def job_seeker(request, public_id, template_name="next_steps/job_seeker.html"):
    """A job seeker's page centred on actions: who follows them, where they stand, what to do, the folded file.

    It shows nothing the existing job seeker page does not: same access rule, same scopes.
    """
    # Same access rule as job_seekers_views.BaseJobSeekerDetailView, within the experiment.
    if not can_view_next_steps(request):
        raise Http404
    job_seeker = get_object_or_404(
        User.objects.select_related("jobseeker_profile"), kind=UserKind.JOB_SEEKER, public_id=public_id
    )

    assignments = list(
        JobSeekerAssignment.objects.filter(job_seeker=job_seeker, ended_at=None)
        .select_related("professional", "company", "prescriber_organization")
        .order_by("-last_action_at")
    )
    # A professional also assigned without organization is shown once, with their organization.
    with_organization = {a.professional_id for a in assignments if a.organization}
    assignments = [a for a in assignments if a.organization or a.professional_id not in with_organization]

    approval = contract = iae_eligibility_diagnosis = None
    if request.from_iae_actor:
        approval = (
            job_seeker.approvals.prefetch_related("suspension_set", "prolongationrequest_set")
            .order_by("-start_at")
            .first()
        )
        iae_eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker, for_siae=request.current_organization if request.from_employer else None
        )
    eligibility_summary = _eligibility_summary(iae_eligibility_diagnosis, approval)
    contracts = []
    if _can_view_contracts(request):
        contract = job_seeker.contracts.select_related("company").order_by("-start_date", "-pk").first()
        contracts = _contracts_for_situation(job_seeker, approval)
    situation_strip = situation_bar(approval) if request.from_iae_actor else None

    actions = [action for action in expected_actions(request) if action.job_seeker.pk == job_seeker.pk]
    show_barriers = request.from_authorized_prescriber or can_fill_pro_support_report(request)
    describe_job_seekers(actions, lambda job_seeker: can_view_personal_information(request, job_seeker))

    context = {
        "job_seeker": job_seeker,
        "can_view_personal_information": can_view_personal_information(request, job_seeker),
        "assignments": assignments,
        # The contracts shown on the strip need no sentence.
        "situation": situation_sentences(request, approval, contract, _can_view_contracts(request) and not contracts),
        "actions": actions,
        "situation_bar": situation_strip,
        # Under the strip: whether a contract runs, and whether the PASS IAE covers it.
        "contract_lines": contract_lines(job_seeker, approval, contracts, functools.partial(contract_place, request))
        if request.from_iae_actor
        else [],
        "show_barriers": show_barriers,
        "barriers": gather_barriers(request, job_seeker, iae_eligibility_diagnosis) if show_barriers else None,
        "file_parts": file_parts(
            request,
            job_seeker,
            approval=approval,
            iae_eligibility_diagnosis=iae_eligibility_diagnosis,
            eligibility_summary=eligibility_summary,
            contracts=contracts,
            can_view_contracts=_can_view_contracts(request),
            # Same rule as the barriers: the reports are one of their sources.
            can_view_report=show_barriers,
            can_view_personal_information=can_view_personal_information(request, job_seeker),
        ),
        "matomo_custom_title": "Prochaines étapes : fiche usager",
        "journeys_media": _journeys_media(request),
    }
    return render(request, template_name, context)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@with_triggers_context
def journey(request, kind, pk):
    """A guided journey: in the side drawer when loaded by htmx, an ordinary page otherwise."""
    if not can_view_next_steps(request) or kind not in JOURNEYS:
        raise Http404
    current_journey = JOURNEYS[kind](request, pk)
    context, completed = engine.run(current_journey, request.POST if request.method == "POST" else None)
    context |= {
        "journey_url": request.path,
        "in_drawer": bool(request.htmx),
        "can_view_name": can_view_personal_information(request, current_journey.job_seeker),
        "matomo_custom_title": f"Prochaines étapes : parcours {kind}",
        "journeys_media": _journeys_media(request),
        "next_action": None,
        "remaining": None,
    }
    if completed:
        # Keep the momentum: what remains today, and the next action to run, right from the confirmation.
        actions = expected_actions(request)
        describe_job_seekers(actions, lambda job_seeker: can_view_personal_information(request, job_seeker))
        context["remaining"] = sum(action.group != Group.WATCH for action in actions)
        context["next_action"] = next_action(actions)
    template_name = "next_steps/journeys/journey.html" if request.htmx else "next_steps/journeys/page.html"
    response = render(request, template_name, context)
    if completed:
        # Pages listening to this event reload their actions.
        response["HX-Trigger"] = "nextStepsChanged"
    return response


@readonly_view
def advisor(request, public_id, assignment_pk):
    """An advisor of the job seeker: who they are, how to reach them, and their acts for the job seeker.

    In the side drawer when loaded by htmx, an ordinary page otherwise. Same access rule as the job seeker's page.
    """
    if not can_view_next_steps(request):
        raise Http404
    job_seeker = get_object_or_404(
        User.objects.select_related("jobseeker_profile"), kind=UserKind.JOB_SEEKER, public_id=public_id
    )
    assignment = get_object_or_404(
        JobSeekerAssignment.objects.select_related("professional", "company", "prescriber_organization"),
        pk=assignment_pk,
        job_seeker=job_seeker,
    )
    assignment.job_seeker = job_seeker
    # One's own assignment: the actions of the existing advisors tab, by its rule (in the organization one is
    # logged into; else, switch to it, or one is no longer a member).
    own = assignment.is_active and assignment.advisor == request.user
    in_its_organization = not assignment.organization or assignment.organization == request.current_organization
    context = {
        "job_seeker": job_seeker,
        "assignment": assignment,
        "can_manage": own and in_its_organization,
        "must_switch": own and not in_its_organization and assignment.is_still_member,
        "has_left": own and not in_its_organization and not assignment.is_still_member,
        "acts": advisor_acts(request, assignment),
        "can_view_name": can_view_personal_information(request, job_seeker),
        "in_drawer": bool(request.htmx),
        "matomo_custom_title": "Prochaines étapes : accompagnateur",
    }
    template_name = "next_steps/advisor.html" if request.htmx else "next_steps/advisor_page.html"
    return render(request, template_name, context)


@readonly_view
def end_assignment(request, public_id, assignment_pk):
    """Confirm the end of one's own assignment, in the side drawer: the existing modal has no place in it.

    The form posts to job_seekers_views.archive_assignment, which checks the same rule: one's own assignment, in the
    organization one is logged into.
    """
    if not can_view_next_steps(request):
        raise Http404
    job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=public_id)
    assignment = get_object_or_404(
        JobSeekerAssignment.objects.select_related("company", "prescriber_organization"),
        pk=assignment_pk,
        job_seeker=job_seeker,
        professional=request.user,
        ended_at=None,
    )
    if assignment.organization and assignment.organization != request.current_organization:
        raise Http404
    context = {
        "job_seeker": job_seeker,
        "assignment": assignment,
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : terminer l’accompagnement",
    }
    return _drawer_or_page(request, "next_steps/end_assignment.html", "Terminer l’accompagnement", context)


@readonly_view
def orientation(request, public_id, orientation_id):
    """An orientation of the job seeker towards a service, from the barriers it works on.

    In the side drawer when loaded by htmx, an ordinary page otherwise. Only an orientation whose details the user
    may read on the orientations tab of the existing job seeker page.
    """
    if not can_view_next_steps(request):
        raise Http404
    job_seeker = get_object_or_404(
        User.objects.select_related("jobseeker_profile"), kind=UserKind.JOB_SEEKER, public_id=public_id
    )
    orientation = get_object_or_404(
        visible_orientations(request, job_seeker)
        .filter(user_can_see_details=True)
        .select_related("service__structure", "sender", "sender_company", "sender_prescriber_organization"),
        pk=orientation_id,
    )
    context = {
        "job_seeker": job_seeker,
        "orientation": orientation,
        "refusal_reasons": [OrientationRefusalReason(reason).label for reason in orientation.refusal_reasons],
        "can_view_name": can_view_personal_information(request, job_seeker),
        "in_drawer": bool(request.htmx),
        "matomo_custom_title": "Prochaines étapes : orientation",
    }
    template_name = "next_steps/orientation.html" if request.htmx else "next_steps/orientation_page.html"
    return render(request, template_name, context)


def _drawer_or_page(request, drawer_template, title, context):
    """In the side drawer when loaded by htmx, an ordinary page otherwise, as when JavaScript does not run."""
    context |= {"in_drawer": bool(request.htmx), "drawer_template": drawer_template, "page_title": title}
    return render(request, drawer_template if request.htmx else "next_steps/drawer_page.html", context)


def _job_seeker_or_404(request, public_id):
    if not can_view_next_steps(request):
        raise Http404
    return get_object_or_404(
        User.objects.select_related("jobseeker_profile"), kind=UserKind.JOB_SEEKER, public_id=public_id
    )


@readonly_view
def job_application(request, public_id, job_application_id):
    """A job application from the job seeker's file: what its "Candidature" section shows on its own page.

    Only a job application whose details the user may read on the job applications tab.
    """
    job_seeker = _job_seeker_or_404(request, public_id)
    job_application = get_object_or_404(
        _job_applications(request, job_seeker)
        .filter(user_can_see_details=True)
        .select_related("sender", "sender_company", "sender_prescriber_organization", "to_company")
        .prefetch_related("selected_jobs__appellation", "selected_jobs__company", "prior_actions"),
        pk=job_application_id,
    )
    context = {
        "job_seeker": job_seeker,
        "job_application": job_application,
        "job_application_sender_left_org": job_application_sender_left_org(job_application),
        "full_url": _job_application_url(request, job_application),
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : candidature",
    }
    return _drawer_or_page(
        request, "next_steps/job_application.html", job_application.to_company.display_name, context
    )


@readonly_view
def suspension(request, public_id, suspension_id):
    """A suspension of the job seeker's PASS IAE, for those who see the PASS IAE in the file."""
    job_seeker = _job_seeker_or_404(request, public_id)
    if not request.from_iae_actor:
        raise Http404
    suspension = get_object_or_404(
        Suspension.objects.filter(approval__user=job_seeker).select_related("approval", "siae"), pk=suspension_id
    )
    context = {
        "job_seeker": job_seeker,
        "suspension": suspension,
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : suspension",
    }
    return _drawer_or_page(request, "next_steps/suspension.html", "Suspension du PASS IAE", context)


@readonly_view
def eligibility(request, public_id):
    """The eligibility diagnosis shown in the job seeker's file: the same one, by the same rule."""
    job_seeker = _job_seeker_or_404(request, public_id)
    if not request.from_iae_actor:
        raise Http404
    diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
        job_seeker, for_siae=request.current_organization if request.from_employer else None
    )
    if diagnosis is None:
        raise Http404
    context = {
        "job_seeker": job_seeker,
        "diagnosis": diagnosis,
        "criteria": diagnosis.selected_administrative_criteria.select_related("administrative_criteria").order_by(
            "administrative_criteria__level", "administrative_criteria__ui_rank"
        ),
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : diagnostic d’éligibilité",
    }
    return _drawer_or_page(request, "next_steps/eligibility.html", "Diagnostic d’éligibilité", context)


@readonly_view
def pro_support_report(request, public_id, report_id):
    """A report on the job seeker, from their file or the queue: what its own page shows, by the same rule."""
    job_seeker = _job_seeker_or_404(request, public_id)
    report = get_object_or_404(
        ProSupportReport.objects.filter(job_seeker=job_seeker).select_related("company", "author"),
        public_id=report_id,
    )
    if not can_view_pro_support_report(request, report):
        raise Http404
    barriers = [(barrier.label, BARRIER_ICONS[barrier]) for barrier in map(ProSupportReportBarrier, report.barriers)]
    if report.other_barrier:
        barriers.append((f"Autre frein : {report.other_barrier}", BARRIER_ICONS[OTHER]))
    context = {
        "job_seeker": job_seeker,
        "report": report,
        "barriers": barriers,
        # Five steps, filled up to the autonomy.
        "autonomy_steps": [step <= report.autonomy for step in range(1, 6)],
        "contract_has_ended": report.contract_end_date < timezone.localdate(),
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : bilan d’accompagnement",
    }
    return _drawer_or_page(request, "next_steps/pro_support_report.html", "Bilan d’accompagnement", context)


@readonly_view
def approval(request, public_id):
    """The job seeker's PASS IAE, as in their file: its strip, period, remainder, suspensions and prolongations.

    Same rule as the PASS IAE's own page, which keeps the actions (suspend, prolong).
    """
    job_seeker = _job_seeker_or_404(request, public_id)
    if not request.from_iae_actor:
        raise Http404
    approval = (
        Approval.objects.filter(user=job_seeker).prefetch_related("suspension_set__siae").order_by("-start_at").first()
    )
    if approval is None or not can_view_approval_details(request, approval):
        raise Http404
    prolongations = [
        {
            "start_at": prolongation.start_at,
            "end_at": prolongation.end_at,
            "reason": prolongation.get_reason_display(),
            "by": prolongation.declared_by_siae.display_name if prolongation.declared_by_siae else "",
            "status": "Acceptée",
            "badge_classes": "bg-success-lighter text-success",
        }
        for prolongation in approval.prolongation_set.select_related("declared_by_siae")
    ] + [
        {
            "start_at": request_.start_at,
            "end_at": request_.end_at,
            "reason": request_.get_reason_display(),
            "by": request_.declared_by_siae.display_name if request_.declared_by_siae else "",
            "status": request_.get_status_display(),
            "badge_classes": "bg-danger-lighter text-danger"
            if request_.status == ProlongationRequestStatus.DENIED
            else "bg-info-lighter text-info",
        }
        # The requests not yet granted: a granted one is a prolongation above.
        for request_ in approval.prolongationrequest_set.filter(prolongation__isnull=True).select_related(
            "declared_by_siae"
        )
    ]
    context = {
        "job_seeker": job_seeker,
        "approval": approval,
        # The PASS IAE alone: the contracts are in the file.
        "bar": situation_bar(approval),
        "suspensions": sorted(approval.suspension_set.all(), key=lambda suspension: suspension.start_at, reverse=True),
        "prolongations": sorted(prolongations, key=lambda prolongation: prolongation["start_at"], reverse=True),
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : PASS IAE",
    }
    return _drawer_or_page(request, "next_steps/approval.html", "PASS IAE", context)


@readonly_view
def contract(request, public_id, contract_id):
    """A contract of the job seeker, from the situation: where, when, how the PASS IAE covers it, its ASP records.

    Only one of the contracts the situation shows, by the rule of the existing contracts tab.
    """
    job_seeker = _job_seeker_or_404(request, public_id)
    if not (request.from_iae_actor and _can_view_contracts(request)):
        raise Http404
    approval = job_seeker.approvals.prefetch_related("suspension_set").order_by("-start_at").first()
    contract = next(
        (contract for contract in _contracts_for_situation(job_seeker, approval) if contract.pk == contract_id), None
    )
    if contract is None:
        raise Http404
    context = {
        "job_seeker": job_seeker,
        "contract": contract,
        "place": contract_place(request, contract),
        "period": period(contract),
        "coverage": coverage(approval, contract),
        "steps": contract_steps(contract),
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : contrat",
    }
    return _drawer_or_page(request, "next_steps/contract.html", "Contrat", context)


class LiftForm(forms.Form):
    """What lifted the barrier, if the professional says: an ongoing orientation on it, or a cause. Never free text."""

    cause = forms.ChoiceField(
        label="Qu’est-ce qui l’a levé ? (facultatif)",
        required=False,
        widget=forms.RadioSelect(attrs={"class": "form-check-input flex-shrink-0"}),
        choices=[],
    )

    def __init__(self, *args, orientations=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.orientations = {f"orientation-{orientation.pk}": orientation for orientation in orientations}
        self.fields["cause"].choices = [
            *(
                (key, f"L’orientation vers «\u00a0{orientation.service.name}\u00a0»")
                for key, orientation in self.orientations.items()
            ),
            (LiftCause.SELF, "La personne a trouvé une solution elle-même"),
            (LiftCause.OTHER, "Autre"),
        ]


STATEMENT_ACTIONS = {"leve": BarrierStatus.LIFTED, "revenu": BarrierStatus.CONFIRMED}


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
def barrier_statement(request, public_id, barrier, action):
    """State a barrier lifted ("leve"), or back to work on ("revenu"), from its card: in the side drawer, then back
    to the job seeker's page.

    For those who see the barriers on the job seeker's page; only the report's barriers, « Autre frein » being free
    text. The statement joins the history the eligibility journey adds to (itou.next_steps.models).
    """
    job_seeker = _job_seeker_or_404(request, public_id)
    key = barrier.upper()
    can_state = request.from_authorized_prescriber or can_fill_pro_support_report(request)
    if not can_state or action not in STATEMENT_ACTIONS or key not in ProSupportReportBarrier.values:
        raise Http404
    status = STATEMENT_ACTIONS[action]
    orientations = [orientation for orientation, keys in ongoing_orientations(request, job_seeker) if key in keys]
    form = LiftForm(data=request.POST or None, orientations=orientations) if status == BarrierStatus.LIFTED else None
    job_seeker_url = reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id})
    if request.method == "POST" and (form is None or form.is_valid()):
        cause = form.cleaned_data["cause"] if form else ""
        orientation = form.orientations.get(cause) if form else None
        JobSeekerBarrier.objects.create(
            job_seeker=job_seeker,
            barrier=key,
            status=status,
            author=request.user,
            author_prescriber_organization=request.current_organization if request.from_prescriber else None,
            author_company=request.current_organization if request.from_employer else None,
            lift_cause=LiftCause.ORIENTATION if orientation else cause,
            orientation=orientation,
        )
        label = ProSupportReportBarrier(key).label
        messages.success(
            request,
            f"Frein «\u00a0{label}\u00a0» "
            + ("levé" if status == BarrierStatus.LIFTED else "de nouveau à travailler"),
            extra_tags="toast",
        )
        return HttpResponseRedirect(job_seeker_url)
    context = {
        "job_seeker": job_seeker,
        "label": ProSupportReportBarrier(key).label,
        "icon": BARRIER_ICONS[key],
        "lifting": status == BarrierStatus.LIFTED,
        "form": form,
        # Back: to work on, or in progress with an orientation still under way on it.
        "back_to": "En cours" if orientations else "À travailler",
        "job_seeker_url": job_seeker_url,
        "can_view_name": can_view_personal_information(request, job_seeker),
        "matomo_custom_title": "Prochaines étapes : frein",
    }
    title = "Frein levé" if status == BarrierStatus.LIFTED else "Frein revenu"
    return _drawer_or_page(request, "next_steps/barrier_statement.html", title, context)
