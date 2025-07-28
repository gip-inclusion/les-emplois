from django import template


register = template.Library()


@register.inclusion_tag("utils/templatetags/approval_box.html")
def approval_details_box(
    approval,
    *,
    detail_view_version=False,
    job_seeker_dashboard_version=False,
    link_from_current_url=None,
    extra_classes="",
):
    return {
        "approval": approval,
        "detail_view_version": detail_view_version,
        "link_from_current_url": link_from_current_url,
        "job_seeker_dashboard_version": job_seeker_dashboard_version,
        "extra_classes": extra_classes,
    }
