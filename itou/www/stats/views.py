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
    METABASE_DASHBOARDS,
    REGION_FILTER_KEY,
    get_view_name,
    metabase_embedded_url,
)
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404


def get_stats_siae_etp_current_org(request):
    current_org = get_current_siae_or_404(request)
    if not request.user.can_view_stats_siae_etp(current_org=current_org):
        raise PermissionDenied
    return current_org


def get_stats_siae_hiring_current_org(request):
    current_org = get_current_siae_or_404(request)
    if not request.user.can_view_stats_siae_hiring(current_org=current_org):
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
    view_name = get_view_name(request)
    metabase_dashboard = METABASE_DASHBOARDS.get(view_name)
    tally_form_id = None
    if settings.TALLY_URL and metabase_dashboard:
        tally_form_id = metabase_dashboard.get("tally_form_id")

    base_context = {
        "iframeurl": metabase_embedded_url(request=request, params=params),
        "stats_base_url": settings.METABASE_SITE_URL,
        "tally_form_id": tally_form_id,
    }

    # Key value pairs in context override preexisting pairs in base_context.
    base_context.update(context)

    matomo_custom_url_prefix = request.resolver_match.route  # e.g. "stats/pe/delay/main"
    base_context["matomo_custom_url"] = f"/{matomo_custom_url_prefix}"
    if "matomo_custom_url_suffix" in base_context:
        matomo_custom_url_suffix = base_context["matomo_custom_url_suffix"]
        del base_context["matomo_custom_url_suffix"]
        # E.g. `/stats/ddets/iae/Provence-Alpes-Cote-d-Azur/04---Alpes-de-Haute-Provence`
        base_context["matomo_custom_url"] += f"/{matomo_custom_url_suffix}"

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


def stats_test1(request):
    context = {
        "page_title": "Test 1 : stats_public clone + tally popup + with the usual iframeResizer",
        "tally_form_id": "waQPkB",
    }
    return render_stats(request=request, context=context, template_name="stats/stats_test1.html")


def stats_test2(request):
    context = {
        "page_title": "Test 2 : stats_public clone + tally popup + *without* the usual iframeResizer",
        "tally_form_id": "waQPkB",
    }
    return render_stats(request=request, context=context, template_name="stats/stats_test2.html")


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
    current_org = get_stats_siae_etp_current_org(request)
    context = {
        "page_title": "Données de ma structure (extranet ASP)",
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(current_org.department),
    }
    return render_stats(
        request=request,
        context=context,
        params={ASP_SIAE_FILTER_KEY: current_org.convention.asp_id},
    )


@login_required
def stats_siae_hiring(request):
    """
    SIAE stats shown only to their own members.
    Employers can see stats for all their SIAEs at once, not just the one currently being worked on.
    These stats are about hiring and are built directly from C1 data.
    """
    current_org = get_stats_siae_hiring_current_org(request)
    context = {
        "page_title": "Données de recrutement de mes structures (Plateforme de l'inclusion)",
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(current_org.department),
    }
    return render_stats(
        request=request,
        context=context,
        params={
            C1_SIAE_FILTER_KEY: [
                str(membership.siae_id) for membership in request.user.active_or_in_grace_period_siae_memberships()
            ]
        },
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
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
    }
    return render_stats(request=request, context=context, params=params)


def render_stats_pe(request, page_title):
    """
    PE ("Pôle emploi") stats shown to relevant members.
    They can view data for their whole departement, not only their agency.
    They cannot view data for other departments than their own.

    `*_main` views are linked directly from the C1 dashboard.
    `*_raw` views are not directly visible on the C1 dashboard but are linked from within their `*_main` counterpart.
    """
    current_org = get_current_org_or_404(request)
    if not request.user.can_view_stats_pe(current_org=current_org):
        raise PermissionDenied
    departments = request.user.get_stats_pe_departments(current_org=current_org)
    params = {
        DEPARTMENT_FILTER_KEY: [DEPARTMENTS[d] for d in departments],
    }
    if current_org.is_dgpe:
        matomo_custom_url_suffix = "dgpe"
    elif current_org.is_drpe:
        matomo_custom_url_suffix = f"{format_region_for_matomo(current_org.region)}/drpe"
    else:
        matomo_custom_url_suffix = format_region_and_department_for_matomo(current_org.department)
    context = {
        "page_title": page_title,
        "matomo_custom_url_suffix": matomo_custom_url_suffix,
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_pe_delay_main(request):
    return render_stats_pe(
        request=request,
        page_title="Délai d'entrée en IAE",
    )


@login_required
def stats_pe_delay_raw(request):
    return render_stats_pe(
        request=request,
        page_title="Données brutes de délai d'entrée en IAE",
    )


@login_required
def stats_pe_conversion_main(request):
    return render_stats_pe(
        request=request,
        page_title="Taux de transformation",
    )


@login_required
def stats_pe_conversion_raw(request):
    return render_stats_pe(
        request=request,
        page_title="Données brutes du taux de transformation",
    )


@login_required
def stats_pe_state_main(request):
    return render_stats_pe(
        request=request,
        page_title="Etat des candidatures orientées",
    )


@login_required
def stats_pe_state_raw(request):
    return render_stats_pe(
        request=request,
        page_title="Données brutes de l’état des candidatures orientées",
    )


@login_required
def stats_pe_tension(request):
    return render_stats_pe(
        request=request,
        page_title="Fiches de poste en tension",
    )


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
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
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
        "page_title": "Données du contrôle a posteriori",
        "back_url": reverse("siae_evaluations_views:samples_selection"),
        "show_diagnosis_control_message": True,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
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
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
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
        "matomo_custom_url_suffix": format_region_for_matomo(region),
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
        "matomo_custom_url_suffix": format_region_for_matomo(region),
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
        "page_title": "Données (version bêta) du contrôle a posteriori",
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


@login_required
def stats_dihal_state(request):
    current_org = get_current_institution_or_404(request)
    if not request.user.can_view_stats_dihal(current_org=current_org):
        raise PermissionDenied
    context = {
        "page_title": "Suivi des prescriptions",
    }
    return render_stats(request=request, context=context, params={})
