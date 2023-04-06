from django import template
from django.utils.safestring import mark_safe

from itou.job_applications.models import JobApplicationWorkflow


register = template.Library()


@register.simple_tag
def state_badge(job_application, *, hx_swap_oob=False):
    state_classes = {
        JobApplicationWorkflow.STATE_ACCEPTED: "badge-success",
        JobApplicationWorkflow.STATE_CANCELLED: "badge-primary",
        JobApplicationWorkflow.STATE_NEW: "badge-info",
        JobApplicationWorkflow.STATE_OBSOLETE: "badge-primary",
        JobApplicationWorkflow.STATE_POSTPONED: "badge-accent-03 text-primary",
        JobApplicationWorkflow.STATE_PRIOR_TO_HIRE: "badge-accent-02 text-primary",
        JobApplicationWorkflow.STATE_PROCESSING: "badge-accent-03 text-primary",
        JobApplicationWorkflow.STATE_REFUSED: "badge-danger",
    }[job_application.state]
    attrs = [
        f'id="state_{ job_application.pk }"',
        f'class="badge badge-sm badge-pill text-wrap mb-1 { state_classes }"',
    ]
    if hx_swap_oob:
        attrs.append('hx-swap-oob="true"')
    return mark_safe(f"<span {' '.join(attrs)}>{ job_application.get_state_display() }</span>")
