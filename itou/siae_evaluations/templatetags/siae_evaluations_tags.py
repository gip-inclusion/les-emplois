from django import template
from django.utils.html import format_html

from itou.siae_evaluations.enums import EvaluatedJobApplicationsState
from itou.siae_evaluations.models import EvaluatedJobApplication
from itou.users.enums import UserKind


register = template.Library()


def badge(content, background_class, text_class):
    return format_html(
        '<span class="badge badge-sm rounded-pill text-nowrap {} {}">{}</span>',
        background_class,
        text_class,
        content,
    )


def danger_badge(content):
    return badge(content, "bg-danger", "text-white")


def warning_badge(content):
    return badge(content, "bg-warning", "text-white")


def info_badge(content):
    return badge(content, "bg-info", "text-white")


def success_badge(content):
    return badge(content, "bg-success", "text-white")


def success_lighter_badge(content):
    return badge(content, "bg-success-lighter", "text-success")


def action_required_badge(content):
    return badge(content, "bg-accent-03", "text-primary")


ACCEPTED_BADGE = success_badge("Validé")
REFUSED_BADGE = danger_badge("Problème constaté")
TODO_BADGE = action_required_badge("À traiter")
UPLOADED_BADGE = action_required_badge("Justificatifs téléversés")


def get_employer_badges(adversarial_stage):
    SUBMITTED_BADGE = success_lighter_badge("Transmis")
    if adversarial_stage:
        return {
            EvaluatedJobApplicationsState.ACCEPTED: ACCEPTED_BADGE,
            EvaluatedJobApplicationsState.UPLOADED: UPLOADED_BADGE,
            EvaluatedJobApplicationsState.SUBMITTED: SUBMITTED_BADGE,
            EvaluatedJobApplicationsState.REFUSED: REFUSED_BADGE,
            EvaluatedJobApplicationsState.REFUSED_2: REFUSED_BADGE,
            EvaluatedJobApplicationsState.PROCESSING: TODO_BADGE,
            EvaluatedJobApplicationsState.PENDING: TODO_BADGE,
        }
    return {
        EvaluatedJobApplicationsState.PENDING: TODO_BADGE,
        EvaluatedJobApplicationsState.PROCESSING: info_badge("En cours"),
        EvaluatedJobApplicationsState.SUBMITTED: SUBMITTED_BADGE,
        EvaluatedJobApplicationsState.UPLOADED: UPLOADED_BADGE,
        # When the institution evaluation is in progress, the institution updates
        # the job application state. Don’t reveal the new state before the review
        # is published.
        EvaluatedJobApplicationsState.ACCEPTED: SUBMITTED_BADGE,
        EvaluatedJobApplicationsState.REFUSED: SUBMITTED_BADGE,
    }


def state_display_for_employer(evaluated_job_application):
    state = evaluated_job_application.compute_state()
    evaluated_siae = evaluated_job_application.evaluated_siae
    if evaluated_siae.evaluation_campaign.ended_at:
        if state in [EvaluatedJobApplicationsState.ACCEPTED, EvaluatedJobApplicationsState.SUBMITTED]:
            return ACCEPTED_BADGE
        return REFUSED_BADGE

    if evaluated_job_application.hide_state_from_siae():
        submitted_state = EvaluatedJobApplicationsState.SUBMITTED
        real_state_priority = EvaluatedJobApplication.STATES_PRIORITY.index(state)
        submitted_state_priority = EvaluatedJobApplication.STATES_PRIORITY.index(submitted_state)
        if real_state_priority < submitted_state_priority:
            state = submitted_state
    return get_employer_badges(bool(evaluated_siae.reviewed_at))[state]


def get_labor_inspector_badges(adversarial_stage, submission_freezed, evaluation_is_final):
    if evaluation_is_final:
        return {
            EvaluatedJobApplicationsState.ACCEPTED: ACCEPTED_BADGE,
            EvaluatedJobApplicationsState.UPLOADED: warning_badge("Justificatifs téléversés"),
            EvaluatedJobApplicationsState.SUBMITTED: badge(
                "Justificatifs non contrôlés", "bg-emploi-light", "text-primary"
            ),
            EvaluatedJobApplicationsState.REFUSED: REFUSED_BADGE,
            EvaluatedJobApplicationsState.REFUSED_2: REFUSED_BADGE,
            EvaluatedJobApplicationsState.PROCESSING: warning_badge("Téléversement incomplet"),
            EvaluatedJobApplicationsState.PENDING: danger_badge("Non téléversés"),
        }

    NOT_SUBMITTED = danger_badge("Justificatifs non transmis")
    if submission_freezed:
        return {
            EvaluatedJobApplicationsState.PENDING: NOT_SUBMITTED,
            EvaluatedJobApplicationsState.PROCESSING: NOT_SUBMITTED,
            EvaluatedJobApplicationsState.UPLOADED: NOT_SUBMITTED,
            EvaluatedJobApplicationsState.SUBMITTED: TODO_BADGE,
            EvaluatedJobApplicationsState.REFUSED: REFUSED_BADGE,
            EvaluatedJobApplicationsState.ACCEPTED: ACCEPTED_BADGE,
            EvaluatedJobApplicationsState.REFUSED_2: REFUSED_BADGE,
        }

    PENDING_BADGE = info_badge("En attente")
    if adversarial_stage:
        return {
            EvaluatedJobApplicationsState.PENDING: PENDING_BADGE,
            EvaluatedJobApplicationsState.PROCESSING: PENDING_BADGE,
            EvaluatedJobApplicationsState.UPLOADED: UPLOADED_BADGE,
            EvaluatedJobApplicationsState.SUBMITTED: TODO_BADGE,
            # Show “Problème constaté” until the review is submitted, which starts
            # the “phase contradictoire” (tracked by the reviewed_at field).
            EvaluatedJobApplicationsState.REFUSED: info_badge("Phase contradictoire - En attente"),
            EvaluatedJobApplicationsState.ACCEPTED: ACCEPTED_BADGE,
            EvaluatedJobApplicationsState.REFUSED_2: REFUSED_BADGE,
        }
    return {
        EvaluatedJobApplicationsState.PENDING: PENDING_BADGE,
        EvaluatedJobApplicationsState.PROCESSING: PENDING_BADGE,
        EvaluatedJobApplicationsState.UPLOADED: UPLOADED_BADGE,
        EvaluatedJobApplicationsState.SUBMITTED: TODO_BADGE,
        EvaluatedJobApplicationsState.REFUSED: REFUSED_BADGE,
        EvaluatedJobApplicationsState.ACCEPTED: ACCEPTED_BADGE,
        EvaluatedJobApplicationsState.REFUSED_2: REFUSED_BADGE,
    }


def state_display_for_labor_inspector(evaluated_job_application):
    state = evaluated_job_application.compute_state()
    evaluated_siae = evaluated_job_application.evaluated_siae
    return get_labor_inspector_badges(
        bool(evaluated_siae.reviewed_at),
        bool(evaluated_siae.submission_freezed_at),
        evaluated_siae.evaluation_is_final,
    )[state]


@register.simple_tag(takes_context=True)
def evaluated_job_application_state_display(context, evaluated_job_application):
    user_kind = context["request"].user.kind
    if user_kind == UserKind.EMPLOYER:
        return state_display_for_employer(evaluated_job_application)
    if user_kind == UserKind.LABOR_INSPECTOR:
        return state_display_for_labor_inspector(evaluated_job_application)
    raise TypeError(f"Unexpected {user_kind=}")
