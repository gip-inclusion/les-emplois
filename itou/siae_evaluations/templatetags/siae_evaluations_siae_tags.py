from django import template
from django.utils.html import format_html

from itou.siae_evaluations.enums import EvaluatedJobApplicationsState
from itou.siae_evaluations.models import EvaluatedJobApplication


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


def info_badge(content):
    return badge(content, "bg-info", "text-white")


def success_badge(content):
    return badge(content, "bg-success", "text-white")


def success_lighter_badge(content):
    return badge(content, "bg-success-lighter", "text-success")


def warning_badge(content):
    return badge(content, "bg-accent-03", "text-primary")


ACCEPTED_BADGE = success_badge("Validé")
PENDING_AFTER_REVIEW_BADGE = warning_badge("Nouveaux justificatifs à traiter")
REFUSED_BADGE = danger_badge("Problème constaté")
SUBMITTED_BADGE = success_lighter_badge("Transmis")
TODO_BADGE = warning_badge("À traiter")
UPLOADED_BADGE = warning_badge("Justificatifs téléversés")

BADGES = {
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

REVIEWED_BADGES = {
    EvaluatedJobApplicationsState.ACCEPTED: ACCEPTED_BADGE,
    EvaluatedJobApplicationsState.UPLOADED: UPLOADED_BADGE,
    EvaluatedJobApplicationsState.SUBMITTED: SUBMITTED_BADGE,
    EvaluatedJobApplicationsState.REFUSED: REFUSED_BADGE,
    EvaluatedJobApplicationsState.REFUSED_2: REFUSED_BADGE,
    EvaluatedJobApplicationsState.PROCESSING: TODO_BADGE,
    EvaluatedJobApplicationsState.PENDING: PENDING_AFTER_REVIEW_BADGE,
}


@register.simple_tag
def evaluated_job_application_state_for_siae(evaluated_job_application):
    state = evaluated_job_application.compute_state()
    if evaluated_job_application.evaluated_siae.evaluation_campaign.ended_at:
        if state in [EvaluatedJobApplicationsState.ACCEPTED, EvaluatedJobApplicationsState.SUBMITTED]:
            return ACCEPTED_BADGE
        return REFUSED_BADGE

    if evaluated_job_application.accepted_from_certified_criteria():
        return ACCEPTED_BADGE

    if evaluated_job_application.hide_state_from_siae():
        submitted_state = EvaluatedJobApplicationsState.SUBMITTED
        real_state_priority = EvaluatedJobApplication.STATES_PRIORITY.index(state)
        submitted_state_priority = EvaluatedJobApplication.STATES_PRIORITY.index(submitted_state)
        if real_state_priority < submitted_state_priority:
            state = submitted_state
    if evaluated_job_application.evaluated_siae.reviewed_at:
        return REVIEWED_BADGES[state]
    return BADGES[state]
