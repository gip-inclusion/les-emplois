"""
Embedding Metabase dashboards:
Metabase dashboards can be included securely in the app via a signed URL
See an embedding sample at:
https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py

Some dashboards have sensitive information and the user should not be able to view data of other departments
than their own, other regions than their own, or other SIAE than their own.

For those dashboards, some filters such as department and/or region and/or SIAE id should be locked on metabase side.
Go to https://stats.inclusion.beta.gouv.fr/dashboard/XXX then "Partage"
then "Partager et intégrer" then "Intégrer ce dashboard dans une application" then inside "Paramètres" on the right,
make sure that the correct filters are "Verrouillé".

"""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS, REGIONS
from itou.utils.apis.metabase import DEPARTMENT_FILTER_KEY, REGION_FILTER_KEY, SIAE_FILTER_KEY, metabase_embedded_url
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


# Each signed dashboard has the same look (at the moment)
_STATS_HTML_TEMPLATE = "stats/stats.html"


def public_basic_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Public basic stats (signed and embedded version)
    Public link:
    https://stats.inclusion.beta.gouv.fr/public/dashboard/f1527a13-1508-498d-8014-b2fe487a3a70
    """
    context = {
        "iframeurl": metabase_embedded_url(settings.PUBLIC_BASIC_STATS_DASHBOARD_ID),
        "page_title": "Statistiques",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@xframe_options_exempt
def public_pilotage_stats(request, dashboard_id, template_name="stats/stats_pilotage.html"):
    """
    We do it because we want to allow users to download chart data which
    is only possible via embedded dashboards and not via public dashboards.
    """
    if dashboard_id not in settings.PILOTAGE_DASHBOARDS_WHITELIST:
        raise PermissionDenied

    context = {
        "iframeurl": metabase_embedded_url(dashboard_id, with_title=True),
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_siae(request, template_name=_STATS_HTML_TEMPLATE):
    """
    SIAE stats shown to their own members.
    They can only view data for their own SIAE.
    """
    current_org = get_current_siae_or_404(request)
    if not request.user.can_view_stats_siae(current_org=current_org):
        raise PermissionDenied
    params = {SIAE_FILTER_KEY: current_org.convention.asp_id}
    context = {
        "iframeurl": metabase_embedded_url(settings.SIAE_STATS_DASHBOARD_ID, params=params),
        "page_title": "Données de ma structure",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_cd(request, template_name=_STATS_HTML_TEMPLATE):
    """
    CD ("Conseil Départemental") stats shown to relevant members.
    They can only view data for their own departement.
    """
    current_org = get_current_org_or_404(request)
    if not request.user.can_view_stats_cd(current_org=current_org):
        raise PermissionDenied
    department = request.user.get_stats_cd_department(current_org=current_org)
    params = {
        DEPARTMENT_FILTER_KEY: DEPARTMENTS[department],
        REGION_FILTER_KEY: DEPARTMENT_TO_REGION[department],
    }
    context = {
        "iframeurl": metabase_embedded_url(settings.CD_STATS_DASHBOARD_ID, params=params),
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_ddets(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_ddets(current_org=current_institution):
        raise PermissionDenied
    department = request.user.get_stats_ddets_department(current_org=current_institution)
    params = {
        DEPARTMENT_FILTER_KEY: DEPARTMENTS[department],
        REGION_FILTER_KEY: DEPARTMENT_TO_REGION[department],
    }
    context = {
        "iframeurl": metabase_embedded_url(settings.DDETS_STATS_DASHBOARD_ID, params=params),
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_dreets(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DREETS ("Directions régionales de l’économie, de l’emploi, du travail et des solidarités") stats shown to
    relevant members. They can only view data for their own region and can filter by department.
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dreets(current_org=current_institution):
        raise PermissionDenied
    region = request.user.get_stats_dreets_region(current_org=current_institution)
    departments = [DEPARTMENTS[dpt] for dpt in REGIONS[region]]
    params = {
        DEPARTMENT_FILTER_KEY: departments,
        REGION_FILTER_KEY: region,
    }
    context = {
        "iframeurl": metabase_embedded_url(settings.DREETS_STATS_DASHBOARD_ID, params=params),
        "page_title": f"Données de ma région : {region}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_dgefp(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dgefp(current_org=current_institution):
        raise PermissionDenied
    params = {
        DEPARTMENT_FILTER_KEY: list(DEPARTMENTS.values()),
        REGION_FILTER_KEY: list(REGIONS.keys()),
    }
    context = {
        "iframeurl": metabase_embedded_url(settings.DGEFP_STATS_DASHBOARD_ID, params=params),
        "page_title": "Données des régions",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)
