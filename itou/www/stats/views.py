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
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS, REGIONS
from itou.utils.apis.metabase import DEPARTMENT_FILTER_KEY, REGION_FILTER_KEY, SIAE_FILTER_KEY, metabase_embedded_url
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


# Each signed dashboard has the same look (at the moment)
_STATS_HTML_TEMPLATE = "stats/stats.html"


def stats_public(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Public basic stats (signed and embedded version)
    Public link:
    https://stats.inclusion.beta.gouv.fr/public/dashboard/f1527a13-1508-498d-8014-b2fe487a3a70
    """
    context = {
        "iframeurl": metabase_embedded_url(request=request),
        "page_title": "Statistiques",
        "stats_base_url": settings.METABASE_SITE_URL,
        "is_stats_public": True,
    }
    return render(request, template_name, context)


@xframe_options_exempt
def stats_pilotage(request, dashboard_id, template_name="stats/stats_pilotage.html"):
    """
    All these dashboard are publicly available on `PILOTAGE_SITE_URL`.
    We do it because we want to allow users to download chart data which
    is only possible via embedded dashboards and not via regular public dashboards.
    """
    if dashboard_id not in settings.PILOTAGE_DASHBOARDS_WHITELIST:
        raise PermissionDenied

    context = {
        "iframeurl": metabase_embedded_url(dashboard_id=dashboard_id, with_title=True),
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
        "iframeurl": metabase_embedded_url(request=request, params=params),
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
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_ddets_iae(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    This dashboard shows data about IAE in general.
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
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_ddets_diagnosis_control(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    This dashboard shows data about diagnosis control ("Contrôle a posteriori").
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
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": "Données 2021 du contrôle a posteriori",
        "stats_base_url": settings.METABASE_SITE_URL,
        "back_url": reverse("siae_evaluations_views:samples_selection"),
    }
    return render(request, template_name, context)


@login_required
def stats_ddets_hiring(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    This dashboard shows data about hiring ("Facilitation de l'embauche").
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_ddets(current_org=current_institution):
        raise PermissionDenied
    department = request.user.get_stats_ddets_department(current_org=current_institution)
    params = {
        DEPARTMENT_FILTER_KEY: DEPARTMENTS[department],
    }
    context = {
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": f"Données facilitation de l'embauche de mon département : {DEPARTMENTS[department]}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_dreets_iae(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DREETS ("Directions régionales de l’économie, de l’emploi, du travail et des solidarités") stats shown to
    relevant members. They can only view data for their own region and can filter by department.
    This dashboard shows data about IAE in general.
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
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": f"Données de ma région : {region}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_dgefp_iae(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    This dashboard shows data about IAE in general.
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dgefp(current_org=current_institution):
        raise PermissionDenied
    params = {
        DEPARTMENT_FILTER_KEY: list(DEPARTMENTS.values()),
        REGION_FILTER_KEY: list(REGIONS.keys()),
    }
    context = {
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": "Données des régions",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_dgefp_diagnosis_control(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    This dashboard shows data about diagnosis control ("Contrôle a posteriori").
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dgefp(current_org=current_institution):
        raise PermissionDenied
    params = {
        DEPARTMENT_FILTER_KEY: list(DEPARTMENTS.values()),
        REGION_FILTER_KEY: list(REGIONS.keys()),
    }
    context = {
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "page_title": "Données 2021 (version bêta) du contrôle a posteriori",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_dgefp_af(request, template_name=_STATS_HTML_TEMPLATE):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    This dashboard shows data about financial annexes ("af").
    """
    current_institution = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dgefp(current_org=current_institution):
        raise PermissionDenied
    context = {
        "iframeurl": metabase_embedded_url(request=request),
        "page_title": "Annexes financières actives",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


def poc_matomo_custom_url(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Simple public route to test Matomo custom URL feature.
    """
    context = {"matomo_custom_url": "/matomo-custom-urls-actually-do-work.html"}
    return render(request, template_name, context)
