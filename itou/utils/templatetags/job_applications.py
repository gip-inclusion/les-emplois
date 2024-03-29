from django import template
from django.utils.safestring import mark_safe

from itou.job_applications.models import JobApplicationWorkflow


register = template.Library()


@register.simple_tag
def state_badge(job_application, *, hx_swap_oob=False, extra_class="badge-sm mb-1"):
    state_classes = {
        JobApplicationWorkflow.STATE_ACCEPTED: "bg-success",
        JobApplicationWorkflow.STATE_CANCELLED: "bg-primary",
        JobApplicationWorkflow.STATE_NEW: "bg-info",
        JobApplicationWorkflow.STATE_OBSOLETE: "bg-primary",
        JobApplicationWorkflow.STATE_POSTPONED: "bg-accent-03 text-primary",
        JobApplicationWorkflow.STATE_PRIOR_TO_HIRE: "bg-accent-02 text-primary",
        JobApplicationWorkflow.STATE_PROCESSING: "bg-accent-03 text-primary",
        JobApplicationWorkflow.STATE_REFUSED: "bg-danger",
    }[job_application.state]
    attrs = [
        f'id="state_{ job_application.pk }"',
        f'class="badge rounded-pill text-wrap { extra_class } { state_classes }"',
    ]
    if hx_swap_oob:
        attrs.append('hx-swap-oob="true"')
    return mark_safe(f"<span {' '.join(attrs)}>{ job_application.get_state_display() }</span>")
