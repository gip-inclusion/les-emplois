from django import template
from django.utils.safestring import mark_safe

from itou.approvals.enums import ApprovalStatus
from itou.job_applications.enums import JobApplicationState


register = template.Library()


@register.simple_tag
def job_application_state_badge(job_application, *, hx_swap_oob=False, extra_class="badge-sm mb-1"):
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
        f'id="state_{job_application.pk}"',
        f'class="badge rounded-pill text-nowrap {extra_class} {state_classes}"',
    ]
    if hx_swap_oob:
        attrs.append('hx-swap-oob="true"')
    badge = f"<span {' '.join(attrs)}>{job_application.get_state_display()}</span>"
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


@register.simple_tag
def approval_state_badge(
    approval, *, force_valid=False, in_approval_box=False, span_extra_class="badge-sm", icon_extra_class=""
):
    # If force_valid is set to True, ignore the provided approval and display a VALID state
    # It is mainly used to show a VALID state to employers instead of SUSPENDED
    # which can be confusing.
    approval_state = ApprovalStatus.VALID if force_valid else approval.state
    if in_approval_box:
        span_class = {
            ApprovalStatus.EXPIRED: "bg-danger text-white",
            ApprovalStatus.FUTURE: "bg-success text-white",
            ApprovalStatus.SUSPENDED: "bg-info text-white",
            ApprovalStatus.VALID: "bg-success text-white",
        }[approval_state]
    else:
        span_class = {
            ApprovalStatus.EXPIRED: "bg-danger-lighter text-danger",
            ApprovalStatus.FUTURE: "bg-success-lighter text-success",
            ApprovalStatus.SUSPENDED: "bg-success-lighter text-success",
            ApprovalStatus.VALID: "bg-success-lighter text-success",
        }[approval_state]
    icon_class = {
        ApprovalStatus.EXPIRED: "ri-pass-expired-line",
        ApprovalStatus.FUTURE: "ri-pass-valid-line",
        ApprovalStatus.SUSPENDED: "ri-pass-pending-line",
        ApprovalStatus.VALID: "ri-pass-valid-line",
    }[approval_state]
    if icon_extra_class:
        icon_class = f"{icon_class} {icon_extra_class}"
    approval_type = "PASS IAE" if approval.is_pass_iae else "Agrément"
    return mark_safe(
        f"""\
            <span class="badge {span_extra_class} rounded-pill {span_class}">
                <i class="{icon_class}" aria-hidden="true"></i>
                {approval_type} {approval_state.label.lower()}
            </span>"""
    )


@register.simple_tag
def iae_eligibility_badge(*, is_eligible, extra_class=""):
    if is_eligible:
        return mark_safe(f"""\
        <span class="badge {extra_class} rounded-pill bg-success-lighter text-success">
            <i class="ri-check-line" aria-hidden="true"></i>
            Éligible à l’IAE
        </span>""")
    else:
        return mark_safe(f"""\
        <span class="badge {extra_class} rounded-pill bg-warning-lighter text-warning">
            <i class="ri-error-warning-line" aria-hidden="true"></i>
            Éligibilité IAE à valider
        </span>""")


@register.simple_tag
def geiq_eligibility_badge(*, is_eligible, extra_class=""):
    if is_eligible:
        return mark_safe(f"""\
        <span class="badge {extra_class} rounded-pill bg-success-lighter text-success">
            <i class="ri-check-line" aria-hidden="true"></i>
            Éligibilité GEIQ confirmée
        </span>""")
    else:
        return mark_safe(f"""\
        <span class="badge {extra_class} rounded-pill bg-warning-lighter text-warning">
            <i class="ri-error-warning-line" aria-hidden="true"></i>
            Éligibilité GEIQ non confirmée
        </span>""")
