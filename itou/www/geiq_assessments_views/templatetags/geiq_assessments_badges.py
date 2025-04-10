from django import template
from django.utils.safestring import mark_safe


register = template.Library()


@register.simple_tag
def state_for_institution(assessment, *, extra_class="badge-sm"):
    if not assessment.submitted_at:
        text = "En attente"
        state_classes = "bg-warning"
    elif not assessment.reviewed_at:
        text = "À contrôler"
        state_classes = "bg-accent-03 text-primary"
    elif not assessment.dreets_reviewed_at:
        text = "À valider"
        state_classes = "bg-info"
    else:
        text = "Validé"
        state_classes = "bg-success"

    class_attr = f"badge rounded-pill text-nowrap {extra_class} {state_classes}"
    return mark_safe(f'<span class="{class_attr}">{text}</span>')
