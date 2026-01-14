from django import template
from django.template.loader import get_template
from django.urls import reverse

from itou.companies.perms import can_create_antenna
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import UserKind
from itou.utils.errors import silently_report_exception


register = template.Library()


@register.simple_tag(takes_context=True)
def structure_switcher(context, mode):
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
            "next_url": reverse("dashboard:index"),
        }
        userkind_context = {
            UserKind.JOB_SEEKER: {
                "icon": "ri-user-line",
                "kind_display": "Candidat",
                "no_org_display": request.user.get_full_name(),
            },
            UserKind.EMPLOYER: {
                "icon": "ri-community-line",
                "kind_display": "Employeur",
                "no_org_display": "Compte inactif",
            },
            UserKind.PRESCRIBER: {
                "icon": (
                    "ri-user-line"
                    if current_organization is None
                    else (
                        "ri-home-smile-line"
                        if current_organization.kind != PrescriberOrganizationKind.OTHER
                        else "ri-group-line"
                    )
                ),
                "kind_display": "Orienteur seul" if current_organization is None else current_organization.kind,
                "no_org_display": request.user.get_full_name(),
            },
            UserKind.LABOR_INSPECTOR: {
                "icon": "ri-government-line",
                "kind_display": "Inspecteur du travail",
                "no_org_display": "Compte inactif",
            },
            UserKind.ITOU_STAFF: {
                "icon": "ri-admin-line",
                "kind_display": "Itou",
                "no_org_display": "Staff",
            },
        }
        template_context.update(userkind_context[request.user.kind])
        template_name = {
            "mobile": "layout/_structure_switcher_offcanvas.html",
            "nav": "layout/_structure_switcher_nav.html",
        }[mode]
        template = get_template(template_name)
        return template.render(template_context)
    except Exception as e:
        silently_report_exception(e)
