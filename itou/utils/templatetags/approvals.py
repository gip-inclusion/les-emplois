from django import template

from itou.approvals.perms import can_view_approval_details


register = template.Library()


@register.inclusion_tag("approvals/includes/box.html")
def approval_details_box(
    approval,
    *,
    request=None,  # Triggers the details link display
    version=None,
    extra_classes="",
):
    assert version in [None, "detail_view", "job_seeker_dashboard"]
    return {
        "approval": approval,
        "request": request,
        "version": version,
        "with_details_link": request and can_view_approval_details(request, approval),
        "extra_classes": extra_classes,
    }
