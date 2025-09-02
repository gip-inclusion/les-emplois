from django import template
from django.template.loader import get_template
from django.utils.safestring import mark_safe

from itou.approvals.enums import ApprovalStatus
from itou.job_applications.enums import JobApplicationState


register = template.Library()


@register.simple_tag
def job_application_state_badge(job_application, *, hx_swap_oob=False, extra_classes="badge-sm mb-1"):
    state_classes = {
        JobApplicationState.ACCEPTED: "bg-success",
        JobApplicationState.CANCELLED: "bg-primary",
        JobApplicationState.NEW: "bg-info",
        JobApplicationState.OBSOLETE: "bg-primary",
        JobApplicationState.POOL: "bg-accent-01 text-white",
        JobApplicationState.POSTPONED: "bg-accent-03 text-primary",
        JobApplicationState.PRIOR_TO_HIRE: "bg-accent-02 text-primary",
        JobApplicationState.PROCESSING: "bg-accent-03 text-primary",
        JobApplicationState.REFUSED: "bg-danger",
    }[job_application.state]
    attrs = [
        f'id="state_{job_application.pk}"',
        f'class="badge rounded-pill text-nowrap {extra_classes} {state_classes}"',
    ]
    if hx_swap_oob:
        attrs.append('hx-swap-oob="true"')
    label = job_application.get_state_display() if job_application.state != JobApplicationState.POOL else "Vivier"
    badge = f"<span {' '.join(attrs)}>{label}</span>"
    if job_application.archived_at:
        badge = f"""{badge}
            <span class="badge rounded-pill {extra_classes} bg-light text-primary"
                  aria-label="candidature archivée"
                  data-bs-toggle="tooltip"
                  data-bs-placement="top"
                  data-bs-title="Candidature archivée">
              <i class="ri-archive-line mx-0"></i>
            </span>"""
    return mark_safe(badge)


@register.simple_tag
def approval_state_badge(
    approval, *, force_valid=False, in_approval_box=False, span_extra_classes="badge-sm", icon_extra_classes=""
):
    # If force_valid is set to True & approval.is_valid(), ignore the provided approval and display a VALID state
    # It is mainly used to show a VALID state to employers instead of SUSPENDED
    # which can be confusing.
    # If the approval is expired, force_valid is ignored.
    approval_state = ApprovalStatus.VALID if force_valid and approval.is_valid() else approval.state
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
    if icon_extra_classes:
        icon_class = f"{icon_class} {icon_extra_classes}"
    return mark_safe(
        f"""\
            <span class="badge {span_extra_classes} rounded-pill {span_class}">
                <i class="{icon_class}" aria-hidden="true"></i>
                PASS IAE {approval_state.label.lower()}
            </span>"""
    )


@register.simple_tag
def iae_eligibility_badge(*, is_eligible, extra_classes="", for_job_seeker=False):
    if is_eligible:
        return mark_safe(f"""\
        <span class="badge {extra_classes} rounded-pill bg-success-lighter text-success">
            <i class="ri-check-line" aria-hidden="true"></i>
            Éligible à l’IAE
        </span>""")
    else:
        span_class = "bg-accent-02-lighter text-primary" if for_job_seeker else "bg-warning-lighter text-warning"
        return mark_safe(f"""\
        <span class="badge {extra_classes} rounded-pill {span_class}">
            <i class="ri-error-warning-line" aria-hidden="true"></i>
            Éligibilité IAE à valider
        </span>""")


@register.simple_tag
def geiq_eligibility_badge(*, is_eligible, extra_classes="", for_job_seeker=False):
    if is_eligible:
        return mark_safe(f"""\
        <span class="badge {extra_classes} rounded-pill bg-success-lighter text-success">
            <i class="ri-check-line" aria-hidden="true"></i>
            Éligibilité GEIQ confirmée
        </span>""")
    else:
        span_class = "bg-accent-02-lighter text-primary" if for_job_seeker else "bg-warning-lighter text-warning"
        return mark_safe(f"""\
        <span class="badge {extra_classes} rounded-pill {span_class}">
            <i class="ri-error-warning-line" aria-hidden="true"></i>
            Éligibilité GEIQ non confirmée
        </span>""")


@register.simple_tag
def criterion_certification_badge(selected_criterion):
    if not selected_criterion.administrative_criteria.is_certifiable:
        return ""

    if selected_criterion.certified_at:
        if selected_criterion.certified is True:
            template = "eligibility/includes/badge_certified.html"
        elif selected_criterion.certified is False:
            template = "eligibility/includes/badge_not_certified.html"
        else:
            template = "eligibility/includes/badge_certification_error.html"
    else:
        template = "eligibility/includes/badge_certification_in_progress.html"
    return get_template(template).render({"extra_classes": "ms-3"})
