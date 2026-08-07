from django import template
from django.urls import reverse

from itou.approvals.perms import can_view_approval_details
from itou.approvals.utils import can_close_approval


register = template.Library()


@register.inclusion_tag("utils/templatetags/approval_box.html")
def approval_details_box(
    approval,
    version,
    *,
    request=None,  # only used in template when details link is displayed
    extra_classes="",
    with_close_action=False,
):
    assert version in [
        "box",  # default version
        "box_without_link",
        "details_view",
        "job_seeker_dashboard",
    ]

    with_link_versions = ["box", "job_seeker_dashboard"]
    assert request or version not in with_link_versions, "request is needed for version='box' or version='details'"

    show_close_approval_button = with_close_action and request and request.from_employer and approval.is_in_progress
    approval_deletion_form_url = None
    if show_close_approval_button and can_close_approval(approval):
        approval_deletion_form_url = reverse(
            "approvals:close",
            kwargs={"approval_id": approval.pk},
            query={"back_url": request.get_full_path()},
        )

    return {
        "approval": approval,
        "request": request,
        "version": version,
        "with_details_link": version in with_link_versions and can_view_approval_details(request, approval),
        "extra_classes": extra_classes,
        "show_close_approval_button": show_close_approval_button,
        "approval_deletion_form_url": approval_deletion_form_url,
    }
