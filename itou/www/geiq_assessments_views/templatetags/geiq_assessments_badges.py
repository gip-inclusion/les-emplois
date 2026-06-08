from django import template
from django.utils.html import format_html

from itou.geiq_assessments.enums import AssessmentState
from itou.utils.templatetags.format_filters import formatfloat_with_unit


register = template.Library()


@register.simple_tag
def state_for_institution(assessment, *, extra_classes="badge-sm"):
    state_classes = {
        AssessmentState.NEW: "bg-warning",
        AssessmentState.SUBMITTED: "bg-accent-03 text-primary",
        AssessmentState.REVIEWED: "bg-info",
        AssessmentState.FINAL_REVIEWED: "bg-success",
    }

    text = AssessmentState(assessment.state).get_label_for_institution()
    class_attr = f"badge rounded-pill text-nowrap {extra_classes} {state_classes[assessment.state]}"
    return format_html('<span class="{}">{}</span>', class_attr, text)


@register.simple_tag
def state_for_geiq(assessment, *, extra_classes="badge-sm"):
    state_classes = {
        AssessmentState.NEW: "bg-info",
        AssessmentState.SUBMITTED: "text-info bg-info-lightest",
        AssessmentState.REVIEWED: "text-info bg-info-lightest",
        AssessmentState.FINAL_REVIEWED: "text-success bg-success-lightest",
    }

    text = AssessmentState(assessment.state).get_label_for_geiq()
    class_attr = f"badge rounded-pill text-nowrap {extra_classes} {state_classes[assessment.state]}"
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
