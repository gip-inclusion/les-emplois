from django import template
from django.utils.html import format_html

from itou.geiq_assessments.enums import AssessmentState
from itou.utils.templatetags.format_filters import formatfloat_with_unit


register = template.Library()


@register.simple_tag
def state_for_institution(assessment, *, extra_classes="badge-sm"):
    match assessment.state:
        case AssessmentState.NEW:
            text = "En attente"
            state_classes = "bg-warning"
        case AssessmentState.SUBMITTED:
            text = "À contrôler"
            state_classes = "bg-accent-03 text-primary"
        case AssessmentState.REVIEWED:
            text = "À valider"
            state_classes = "bg-info"
        case AssessmentState.FINAL_REVIEWED:
            text = "Validé"
            state_classes = "bg-success"
        case _:
            raise ValueError(f"Wrong state {assessment.state}")

    class_attr = f"badge rounded-pill text-nowrap {extra_classes} {state_classes}"
    return format_html('<span class="{}">{}</span>', class_attr, text)


@register.simple_tag
def state_for_geiq(assessment, *, extra_classes="badge-sm"):
    match assessment.state:
        case AssessmentState.NEW:
            text = "À compléter"
            state_classes = "bg-info"
        case AssessmentState.SUBMITTED | AssessmentState.REVIEWED:
            text = "Envoyé"
            state_classes = "text-info bg-info-lightest"
        case AssessmentState.FINAL_REVIEWED:
            text = "Traité"
            state_classes = "text-success bg-success-lightest"
        case _:
            raise ValueError("Wrong state {assessment.state}")

    class_attr = f"badge rounded-pill text-nowrap {extra_classes} {state_classes}"
    return format_html('<span class="{}">{}</span>', class_attr, text)


@register.simple_tag
def grant_percentage_badge(assessment, *, extra_classes="badge-sm"):
    if assessment.convention_amount:
        grant_percentage = 100 * assessment.granted_amount / assessment.convention_amount
        if grant_percentage == 100:
            state_classes = "bg-success-lighter text-success"
        else:
            state_classes = "bg-warning-lighter text-warning"
        class_attr = f"badge rounded-pill text-nowrap {extra_classes} {state_classes}"
        return format_html('<span class="{}">{}</span>', class_attr, formatfloat_with_unit(grant_percentage, "%"))
    return "-"
