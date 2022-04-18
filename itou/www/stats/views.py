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

from itou.common_apps.address.departments import (
    DEPARTMENT_TO_REGION,
    DEPARTMENTS,
    REGIONS,
    format_region_and_department_for_matomo,
    format_region_for_matomo,
)
from itou.utils.apis.metabase import (
    ASP_SIAE_FILTER_KEY,
    C1_SIAE_FILTER_KEY,
    DEPARTMENT_FILTER_KEY,
    REGION_FILTER_KEY,
    metabase_embedded_url,
)
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


def get_stats_siae_current_org(request):
    current_org = get_current_siae_or_404(request)
    if not request.user.can_view_stats_siae(current_org=current_org):
        raise PermissionDenied
    return current_org


def get_stats_ddets_department(request):
    current_org = get_current_institution_or_404(request)
    if not request.user.can_view_stats_ddets(current_org=current_org):
        raise PermissionDenied
    department = request.user.get_stats_ddets_department(current_org=current_org)
    return department


def get_stats_dreets_region(request):
    current_org = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dreets(current_org=current_org):
        raise PermissionDenied
    region = request.user.get_stats_dreets_region(current_org=current_org)
    return region


def ensure_stats_dgefp_permission(request):
    current_org = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dgefp(current_org=current_org):
        raise PermissionDenied


def get_params_for_departement(department):
    return {
        DEPARTMENT_FILTER_KEY: DEPARTMENTS[department],
        REGION_FILTER_KEY: DEPARTMENT_TO_REGION[department],
    }


def get_params_for_region(region):
    departments = [DEPARTMENTS[dpt] for dpt in REGIONS[region]]
    params = {
        DEPARTMENT_FILTER_KEY: departments,
        REGION_FILTER_KEY: region,
    }
    return params


def get_params_for_whole_country():
    return {
        DEPARTMENT_FILTER_KEY: list(DEPARTMENTS.values()),
        REGION_FILTER_KEY: list(REGIONS.keys()),
    }


def render_stats(request, context, params={}, template_name="stats/stats.html"):
    base_context = {
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    # Key value pairs in context override preexisting pairs in base_context.
    base_context.update(context)
    return render(request, template_name, base_context)


def stats_public(request):
    """
    Public basic stats (signed and embedded version)
    """
    context = {
        "page_title": "Statistiques",
        "is_stats_public": True,
    }
    return render_stats(request=request, context=context)


@xframe_options_exempt
def stats_pilotage(request, dashboard_id):
    """
    All these dashboard are publicly available on `PILOTAGE_SITE_URL`.
    We do it because we want to allow users to download chart data which
    is only possible via embedded dashboards and not via regular public dashboards.
    """
    if dashboard_id not in settings.PILOTAGE_DASHBOARDS_WHITELIST:
        raise PermissionDenied

    context = {
        "iframeurl": metabase_embedded_url(dashboard_id=dashboard_id, with_title=True),
    }
    return render_stats(request=request, context=context, template_name="stats/stats_pilotage.html")


@login_required
def stats_siae_etp(request):
    """
    SIAE stats shown to their own members.
    They can only view data for their own SIAE.
    These stats are about ETP data from the ASP.
    """
    current_org = get_stats_siae_current_org(request)
    context = {
        "page_title": "Données de ma structure (extranet ASP)",
        "matomo_custom_url": f"/stats/siae/etp/{format_region_and_department_for_matomo(current_org.department)}",
    }
    return render_stats(
        request=request,
        context=context,
        params={ASP_SIAE_FILTER_KEY: current_org.convention.asp_id},
    )


@login_required
def stats_siae_hiring(request):
    """
    SIAE stats shown to their own members.
    They can only view data for their own SIAE.
    These stats are about hiring and are built directly from C1 data.
    """
    current_org = get_stats_siae_current_org(request)
    context = {
        "page_title": "Données de recrutement de ma structure (Plateforme de l'inclusion)",
        "matomo_custom_url": f"/stats/siae/hiring/{format_region_and_department_for_matomo(current_org.department)}",
    }
    return render_stats(
        request=request,
        context=context,
        params={C1_SIAE_FILTER_KEY: str(current_org.id)},
    )


@login_required
def stats_cd(request):
    """
    CD ("Conseil Départemental") stats shown to relevant members.
    They can only view data for their own departement.
    """
    current_org = get_current_org_or_404(request)
    if not request.user.can_view_stats_cd(current_org=current_org):
        raise PermissionDenied
    department = request.user.get_stats_cd_department(current_org=current_org)
    params = get_params_for_departement(department)
    context = {
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "matomo_custom_url": f"/stats/cd/{format_region_and_department_for_matomo(department)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_pe(request):
    """
    PE ("Pôle emploi") stats shown to relevant members.
    They can view data for their whole departement, not only their agency.
    They cannot view data for other departments than their own.
    """
    current_org = get_current_org_or_404(request)
    if not request.user.can_view_stats_pe(current_org=current_org):
        raise PermissionDenied
    department = request.user.get_stats_pe_department(current_org=current_org)
    params = {
        DEPARTMENT_FILTER_KEY: DEPARTMENTS[department],
    }
    context = {
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "matomo_custom_url": f"/stats/pe/{format_region_and_department_for_matomo(department)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_ddets_iae(request):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    This dashboard shows data about IAE in general.
    """
    department = get_stats_ddets_department(request)
    params = get_params_for_departement(department)
    context = {
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "matomo_custom_url": f"/stats/ddets/iae/{format_region_and_department_for_matomo(department)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_ddets_diagnosis_control(request):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    This dashboard shows data about diagnosis control ("Contrôle a posteriori").
    """
    department = get_stats_ddets_department(request)
    params = get_params_for_departement(department)
    context = {
        "page_title": "Données 2021 du contrôle a posteriori",
        "back_url": reverse("siae_evaluations_views:samples_selection"),
        "show_diagnosis_control_message": True,
        "matomo_custom_url": f"/stats/ddets/diagnosis_control/{format_region_and_department_for_matomo(department)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_ddets_hiring(request):
    """
    DDETS ("Directions départementales de l’emploi, du travail et des solidarités") stats shown to relevant members.
    They can only view data for their own departement.
    This dashboard shows data about hiring ("Facilitation de l'embauche").
    """
    department = get_stats_ddets_department(request)
    params = get_params_for_departement(department)
    context = {
        "page_title": f"Données facilitation de l'embauche de mon département : {DEPARTMENTS[department]}",
        "matomo_custom_url": f"/stats/ddets/hiring/{format_region_and_department_for_matomo(department)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_dreets_iae(request):
    """
    DREETS ("Directions régionales de l’économie, de l’emploi, du travail et des solidarités") stats shown to
    relevant members. They can only view data for their own region and can filter by department.
    This dashboard shows data about IAE in general.
    """
    region = get_stats_dreets_region(request)
    params = get_params_for_region(region)
    context = {
        "page_title": f"Données de ma région : {region}",
        "matomo_custom_url": f"/stats/dreets/iae/{format_region_for_matomo(region)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_dreets_hiring(request):
    """
    DREETS ("Directions régionales de l’économie, de l’emploi, du travail et des solidarités") stats shown to
    relevant members. They can only view data for their own region and can filter by department.
    This dashboard shows data about hiring ("Facilitation de l'embauche").
    """
    region = get_stats_dreets_region(request)
    params = get_params_for_region(region)
    context = {
        "page_title": f"Données facilitation de l'embauche de ma région : {region}",
        "matomo_custom_url": f"/stats/dreets/hiring/{format_region_for_matomo(region)}",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_dgefp_iae(request):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    This dashboard shows data about IAE in general.
    """
    ensure_stats_dgefp_permission(request)
    params = get_params_for_whole_country()
    context = {
        "page_title": "Données des régions",
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_dgefp_diagnosis_control(request):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    This dashboard shows data about diagnosis control ("Contrôle a posteriori").
    """
    ensure_stats_dgefp_permission(request)
    params = get_params_for_whole_country()
    context = {
        "page_title": "Données 2021 (version bêta) du contrôle a posteriori",
        "show_diagnosis_control_message": True,
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_dgefp_af(request):
    """
    DGEFP ("délégation générale à l'Emploi et à la Formation professionnelle") stats shown to relevant members.
    They can view all data and filter by region and/or department.
    This dashboard shows data about financial annexes ("af").
    """
    ensure_stats_dgefp_permission(request)
    context = {
        "page_title": "Annexes financières actives",
    }
    return render_stats(request=request, context=context)
