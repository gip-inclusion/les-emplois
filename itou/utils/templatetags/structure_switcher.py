from django import template
from django.template.loader import get_template

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.errors import silently_report_exception


register = template.Library()


@register.simple_tag(takes_context=True)
def structure_switcher(context, mobile):
    try:
        request = context["request"]
        current_organization = getattr(request, "current_organization", None)
        organizations = getattr(request, "organizations", [])
        template_context = {
            "csrf_token": context["csrf_token"],
            "current_organization": current_organization,
            "organizations": organizations,
            "show_switcher": len(organizations) > 1,
            "user": request.user,
        }
        if request.user.is_employer:
            icon = "ri-community-line"
        elif request.user.is_prescriber:
            icon = (
                "ri-home-smile-line"
                if current_organization and current_organization.kind != PrescriberOrganizationKind.OTHER
                else "ri-group-line"
            )
        else:
            icon = "ri-government-line"
        template_context["icon"] = icon
        template_name = (
            "layout/_structure_switcher_dropdown_menu.html" if mobile else "layout/_structure_switcher.html"
        )
        template = get_template(template_name)
        return template.render(template_context)
    except Exception as e:
        silently_report_exception(e)
