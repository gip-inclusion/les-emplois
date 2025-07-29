from django import template


register = template.Library()


@register.inclusion_tag("utils/templatetags/approval_box.html")
def approval_details_box(
    approval,
    request,  # only used in template when hide_details_link is False
    *,
    hide_details_link=False,
    version=None,
    extra_classes="",
):
    assert version in [None, "detail_view", "job_seeker_dashboard"]
    return {
        "approval": approval,
        "request": request,
        "version": version,
        "with_details_link": hide_details_link is False,
        "extra_classes": extra_classes,
    }
