from django import template
from django.utils.html import format_html

from itou.utils.templatetags.format_filters import formatfloat_with_unit


register = template.Library()


@register.simple_tag
def state_for_institution(assessment, *, extra_class="badge-sm"):
    if not assessment.submitted_at:
        text = "En attente"
        state_classes = "bg-warning"
    elif not assessment.reviewed_at:
        text = "À contrôler"
        state_classes = "bg-accent-03 text-primary"
    elif not assessment.final_reviewed_at:
        text = "À valider"
        state_classes = "bg-info"
    else:
        text = "Validé"
        state_classes = "bg-success"

    class_attr = f"badge rounded-pill text-nowrap {extra_class} {state_classes}"
    return format_html('<span class="{}">{}</span>', class_attr, text)


@register.simple_tag
def state_for_geiq(assessment, *, extra_class="badge-sm"):
    if not assessment.submitted_at:
        text = "À compléter"
        state_classes = "bg-info"
    elif not assessment.final_reviewed_at:
        text = "Envoyé"
        state_classes = "text-info bg-info-lightest"
    else:
        text = "Traité"
        state_classes = "text-success bg-success-lightest"

    class_attr = f"badge rounded-pill text-nowrap {extra_class} {state_classes}"
    return format_html('<span class="{}">{}</span>', class_attr, text)


@register.simple_tag
def grant_percentage_badge(assessment, *, extra_class="badge-sm"):
    if assessment.convention_amount:
        grant_percentage = 100 * assessment.granted_amount / assessment.convention_amount
        if grant_percentage == 100:
            state_classes = "bg-success-lighter text-success"
        else:
            state_classes = "bg-warning-lighter text-warning"
        class_attr = f"badge rounded-pill text-nowrap {extra_class} {state_classes}"
        return format_html('<span class="{}">{}</span>', class_attr, formatfloat_with_unit(grant_percentage, "%"))
    return "-"
