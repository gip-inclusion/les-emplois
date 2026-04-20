from django import template
from django.template.loader import get_template
from django.urls import reverse

from itou.companies.perms import can_create_antenna
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.errors import silently_report_exception


register = template.Library()


@register.simple_tag(takes_context=True)
def organization_switcher(context, mode):
    try:
        request = context["request"]
        current_organization = getattr(request, "current_organization", None)
        organizations = getattr(request, "organizations", [])
        create_antenna_perm = can_create_antenna(request)
        template_context = {
            "can_create_antenna": create_antenna_perm,
            "csrf_token": context["csrf_token"],
            "current_organization": current_organization,
            "organizations": organizations,
            "show_company_switcher_menu": len(organizations) >= 2 or create_antenna_perm,
            "user": request.user,
            "next_url": reverse("nexus:emplois") if mode == "nexus" else reverse("dashboard:index"),
        }
        if request.user.is_job_seeker:
            userkind_context = {
                "icon": "ri-user-line",
                "kind_display": "Candidat",
                "no_org_display": request.user.get_full_name(),
            }
        elif request.from_employer:
            userkind_context = {
                "icon": "ri-community-line",
                # kind_display and no_org_display are never used since there's always an organization
            }
        elif request.from_prescriber:
            userkind_context = {
                "icon": (
                    "ri-home-smile-line"
                    if current_organization.kind != PrescriberOrganizationKind.OTHER
                    else "ri-group-line"
                )
                # kind_display and no_org_display are never used since there's always an organization
            }
        elif request.from_institution:
            userkind_context = {
                "icon": "ri-government-line",
                # kind_display and no_org_display are never used since there's always an organization
            }
        elif request.user.is_professional:
            # This means current organization is None
            userkind_context = {
                "icon": "ri-user-line",
                "kind_display": "Professionel",
                "no_org_display": request.user.get_full_name(),
            }
        elif request.user.is_itou_staff:
            userkind_context = {
                "icon": "ri-admin-line",
                "kind_display": "Itou",
                "no_org_display": "Staff",
            }
        template_context.update(userkind_context)
        template_name = {
            "mobile": "layout/_organization_switcher_offcanvas.html",
            "nav": "layout/_organization_switcher_nav.html",
            "nexus": "layout/_organization_switcher_nexus.html",
        }[mode]
        template = get_template(template_name)
        return template.render(template_context)
    except Exception as e:
        silently_report_exception(e)
