from dateutil.relativedelta import relativedelta
from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from itou.approvals.utils import get_contracts
from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.users.perms import (
    add_user_can_view_personal_information,
    can_fill_pro_support_report,
    can_view_pro_support_report,
)
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.views import with_triggers_context
from itou.www.next_steps_views import engine
from itou.www.next_steps_views.access import can_view_next_steps
from itou.www.next_steps_views.actions import Group, expected_actions, group_actions
from itou.www.next_steps_views.journeys import JOURNEYS
from itou.www.next_steps_views.situation import situation_sentences
from itou.www.next_steps_views.timeline import build_timeline


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
    add_user_can_view_personal_information(
        actions, lambda job_seeker: can_view_personal_information(request, job_seeker)
    )
    context = {
        "groups": group_actions(actions),
        "pressing_count": sum(action.group != Group.WATCH for action in actions),
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


def _contracts_for_timeline(job_seeker, approval):
    # Same contracts as job_seekers_views.ContractsTabView.
    if approval is None or not approval.is_valid:
        two_years_ago = timezone.localdate() - relativedelta(years=2)
        contracts = job_seeker.contracts.exclude(end_date__lt=two_years_ago)
    else:
        contracts = get_contracts(approval)
    return list(contracts.select_related("company").order_by("start_date"))


def _last_viewable_pro_support_report(request, job_seeker):
    """The barriers come from the latest report: the only place where the platform records them."""
    reports = job_seeker.pro_support_reports.select_related("company").order_by("-created_at")
    if request.from_employer:
        reports = reports.filter(company=request.current_organization)
    report = reports.first()
    if report and can_view_pro_support_report(request, report):
        return report
    return None


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
    contracts = None
    if _can_view_contracts(request):
        contract = job_seeker.contracts.select_related("company").order_by("-start_date", "-pk").first()
        contracts = _contracts_for_timeline(job_seeker, approval)
    timeline = build_timeline(
        approvals=([approval] if approval else []) if request.from_iae_actor else None,
        contracts=contracts,
    )

    actions = [action for action in expected_actions(request) if action.job_seeker.pk == job_seeker.pk]
    for action in actions:
        action.user_can_view_personal_information = can_view_personal_information(request, job_seeker)

    context = {
        "job_seeker": job_seeker,
        "can_view_personal_information": can_view_personal_information(request, job_seeker),
        "assignments": assignments,
        "situation": situation_sentences(request, approval, contract, _can_view_contracts(request)),
        "actions": actions,
        "approval": approval,
        "contract": contract,
        "can_view_contracts": _can_view_contracts(request),
        "iae_eligibility_diagnosis": iae_eligibility_diagnosis,
        "eligibility_summary": eligibility_summary,
        "timeline": timeline,
        "show_barriers": request.from_authorized_prescriber or can_fill_pro_support_report(request),
        "pro_support_report": _last_viewable_pro_support_report(request, job_seeker),
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
    }
    template_name = "next_steps/journeys/journey.html" if request.htmx else "next_steps/journeys/page.html"
    response = render(request, template_name, context)
    if completed:
        # Pages listening to this event reload their actions.
        response["HX-Trigger"] = "nextStepsChanged"
    return response
