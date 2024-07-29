from django import template
from django.utils.safestring import mark_safe

from itou.job_applications.enums import JobApplicationState


register = template.Library()


@register.simple_tag
def state_badge(job_application, *, hx_swap_oob=False, extra_class="badge-sm mb-1"):
    state_classes = {
        JobApplicationState.ACCEPTED: "bg-success",
        JobApplicationState.CANCELLED: "bg-primary",
        JobApplicationState.NEW: "bg-info",
        JobApplicationState.OBSOLETE: "bg-primary",
        JobApplicationState.POSTPONED: "bg-accent-03 text-primary",
        JobApplicationState.PRIOR_TO_HIRE: "bg-accent-02 text-primary",
        JobApplicationState.PROCESSING: "bg-accent-03 text-primary",
        JobApplicationState.REFUSED: "bg-danger",
    }[job_application.state]
    attrs = [
        f'id="state_{ job_application.pk }"',
        f'class="badge rounded-pill text-nowrap { extra_class } { state_classes }"',
    ]
    if hx_swap_oob:
        attrs.append('hx-swap-oob="true"')
    badge = f"<span {' '.join(attrs)}>{ job_application.get_state_display() }</span>"
    if job_application.archived_at:
        badge = f"""\
            <span class="badge rounded-pill {extra_class} bg-light text-primary"
                  aria-label="candidature archivée"
                  data-bs-toggle="tooltip"
                  data-bs-placement="top"
                  data-bs-title="Candidature archivée">
              <i class="ri-archive-line mx-0"></i>
            </span>{badge}"""
    return mark_safe(badge)
