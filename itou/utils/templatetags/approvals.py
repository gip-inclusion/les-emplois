from django import template

from itou.approvals.perms import can_view_approval_details


register = template.Library()


@register.inclusion_tag("utils/templatetags/approval_box.html")
def approval_details_box(
    approval,
    version,
    *,
    request=None,  # only used in template when details link is displayed
    extra_classes="",
):
    assert version in [
        "box",  # default version
        "box_without_link",
        "details_view",
        "job_seeker_dashboard",
    ]

    with_link_versions = ["box", "job_seeker_dashboard"]
    assert request or version not in with_link_versions, "request is needed for version='box' or version='details'"

    return {
        "approval": approval,
        "request": request,
        "version": version,
        "with_details_link": version in with_link_versions and can_view_approval_details(request, approval),
        "extra_classes": extra_classes,
    }
