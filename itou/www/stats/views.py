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

from itou.analytics.models import StatsDashboardVisit
from itou.common_apps.address.departments import (
    DEPARTMENT_TO_REGION,
    DEPARTMENTS,
    REGIONS,
    format_region_and_department_for_matomo,
    format_region_for_matomo,
)
from itou.companies import models as companies_models
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils import constants as global_constants
from itou.utils.apis import metabase as mb
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404

from . import utils


def get_stats_siae_current_org(request):
    current_org = get_current_company_or_404(request)
    if not utils.can_view_stats_siae(request):
        raise PermissionDenied
    return current_org


def get_stats_dreets_iae_region(request):
    current_org = get_current_institution_or_404(request)
    if not utils.can_view_stats_dreets_iae(request):
        raise PermissionDenied
    return current_org.region


def ensure_stats_dgefp_permission(request):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_dgefp(request):
        raise PermissionDenied


def get_params_for_departement(department):
    return {
        mb.DEPARTMENT_FILTER_KEY: DEPARTMENTS[department],
        mb.REGION_FILTER_KEY: DEPARTMENT_TO_REGION[department],
    }


def get_params_for_region(region):
    departments = [DEPARTMENTS[dpt] for dpt in REGIONS[region]]
    params = {
        mb.DEPARTMENT_FILTER_KEY: departments,
        mb.REGION_FILTER_KEY: region,
    }
    return params


def get_params_for_idf_region():
    return get_params_for_region("Île-de-France")


def get_params_for_whole_country():
    return {
        mb.DEPARTMENT_FILTER_KEY: list(DEPARTMENTS.values()),
        mb.REGION_FILTER_KEY: list(REGIONS.keys()),
    }


def get_params_aci_asp_ids_for_department(department):
    return {
        mb.ASP_SIAE_FILTER_KEY_FLAVOR2: list(
            companies_models.Company.objects.filter(
                kind=companies_models.CompanyKind.ACI,
                department=department,
                # By only taking ASP-imported SIAE and because we are using the `asp_id`:
                # - antennas in the department with a convention signed in another department are filter out
                # - antennas not in the department with a convention signed in the department are included
                source=companies_models.Company.SOURCE_ASP,
            )
            .select_related("convention")
            .values_list("convention__asp_id", flat=True)
        )
    }


def render_stats(request, context, params=None, template_name="stats/stats.html"):
    if params is None:
        params = {}
    view_name = mb.get_view_name(request)
    metabase_dashboard = mb.METABASE_DASHBOARDS.get(view_name)
    tally_popup_form_id = None
    tally_embed_form_id = None
    if settings.TALLY_URL and metabase_dashboard:
        tally_popup_form_id = metabase_dashboard.get("tally_popup_form_id")
        tally_embed_form_id = metabase_dashboard.get("tally_embed_form_id")

    base_context = {
        "back_url": None,
        "iframeurl": mb.metabase_embedded_url(request=request, params=params),
        "is_stats_public": False,
        "show_siae_evaluation_message": False,
        "stats_base_url": settings.METABASE_SITE_URL,
        "tally_popup_form_id": tally_popup_form_id,
        "tally_embed_form_id": tally_embed_form_id,
        "PILOTAGE_HELP_CENTER_URL": global_constants.PILOTAGE_HELP_CENTER_URL,
    }

    # Key value pairs in context override preexisting pairs in base_context.
    base_context.update(context)

    matomo_custom_url = request.resolver_match.route  # e.g. "stats/pe/delay/main"
    if suffix := base_context.pop("matomo_custom_url_suffix", None):
        # E.g. `/stats/ddets/iae/Provence-Alpes-Cote-d-Azur/04---Alpes-de-Haute-Provence`
        matomo_custom_url += f"/{suffix}"
    base_context["matomo_custom_url"] = matomo_custom_url

    if request.user.is_authenticated and metabase_dashboard:
        company_id = request.current_organization.pk if request.user.is_employer else None
        prescriber_org_pk = request.current_organization.pk if request.user.is_prescriber else None
        institution_pk = request.current_organization.pk if request.user.is_labor_inspector else None
        user_kind = request.user.kind
        department = base_context.get("department")
        region = DEPARTMENT_TO_REGION[department] if department else base_context.get("region")
        dashboard_id = metabase_dashboard.get("dashboard_id")
        StatsDashboardVisit.objects.create(
            dashboard_id=dashboard_id,
            dashboard_name=view_name,
            department=department,
            region=region,
            current_company_id=company_id,
            current_prescriber_organization_id=prescriber_org_pk,
            current_institution_id=institution_pk,
            user_kind=user_kind,
            user_id=request.user.pk,
        )

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
        "iframeurl": mb.metabase_embedded_url(dashboard_id=dashboard_id, with_title=True),
    }
    return render_stats(request=request, context=context, template_name="stats/stats_pilotage.html")


@login_required
def stats_siae_aci(request):
    """
    ACI stats shown to their own members.
    They can only view data for their own ACI.
    """
    current_org = get_stats_siae_current_org(request)
    if not utils.can_view_stats_siae_aci(request):
        raise PermissionDenied
    context = {
        "page_title": "Suivi du cofinancement de mon ACI",
        "department": current_org.department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(current_org.department),
    }
    return render_stats(
        request=request,
        context=context,
        params={mb.ASP_SIAE_FILTER_KEY_FLAVOR2: current_org.convention.asp_id},
    )


@login_required
def stats_siae_etp(request):
    """
    SIAE stats shown to their own members.
    They can only view data for their own SIAE.
    These stats are about ETP data from the ASP.
    """
    current_org = get_stats_siae_current_org(request)
    if not utils.can_view_stats_siae_etp(request):
        raise PermissionDenied
    context = {
        "page_title": "Suivi des effectifs annuels et mensuels en ETP",
        "department": current_org.department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(current_org.department),
    }
    return render_stats(
        request=request,
        context=context,
        params={
            mb.ASP_SIAE_FILTER_KEY_FLAVOR3: [
                str(membership.company.convention.asp_id)
                for membership in request.user.active_or_in_grace_period_company_memberships()
            ]
        },
    )


def render_stats_siae(request, page_title):
    """
    SIAE stats shown only to their own members.
    Employers can see stats for all their SIAEs at once, not just the one currently being worked on.
    These stats are built directly from C1 data.
    """
    current_org = get_stats_siae_current_org(request)
    context = {
        "page_title": page_title,
        "department": current_org.department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(current_org.department),
    }
    return render_stats(
        request=request,
        context=context,
        params={
            mb.C1_SIAE_FILTER_KEY: [
                str(membership.company_id)
                for membership in request.user.active_or_in_grace_period_company_memberships()
            ]
        },
    )


@login_required
def stats_siae_hiring(request):
    return render_stats_siae(request=request, page_title="Données de candidatures de mes structures")


@login_required
def stats_siae_auto_prescription(request):
    return render_stats_siae(request=request, page_title="Focus auto-prescription")


@login_required
def stats_siae_follow_siae_evaluation(request):
    return render_stats_siae(request=request, page_title="Suivi du contrôle a posteriori")


@login_required
def stats_siae_hiring_report(request):
    if not utils.can_view_stats_siae_hiring_report(request):
        raise PermissionDenied
    return render_stats_siae(request=request, page_title="Déclaration d’embauche")


def render_stats_cd(request, page_title, params=None):
    """
    CD ("Conseil Départemental") stats shown to relevant members.
    They can only view data for their own departement.
    """
    current_org = get_current_org_or_404(request)
    if not utils.can_view_stats_cd(request):
        raise PermissionDenied
    department = current_org.department
    params = get_params_for_departement(department) if params is None else params
    context = {
        "page_title": f"{page_title} de mon département : {DEPARTMENTS[department]}",
        "department": department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_cd_iae(request):
    return render_stats_cd(request=request, page_title="Données IAE")


@login_required
def stats_cd_hiring(request):
    if not utils.can_view_stats_cd_whitelist(request):
        raise PermissionDenied
    return render_stats_cd(request=request, page_title="Facilitation des embauches en IAE")


@login_required
def stats_cd_brsa(request):
    if not utils.can_view_stats_cd_whitelist(request):
        raise PermissionDenied
    return render_stats_cd(request=request, page_title="Suivi des prescriptions des accompagnateurs des publics bRSA")


@login_required
def stats_cd_aci(request):
    current_org = get_current_org_or_404(request)
    if not utils.can_view_stats_cd_aci(request):
        raise PermissionDenied

    return render_stats_cd(
        request=request,
        page_title="Suivi du cofinancement des ACI",
        params=get_params_aci_asp_ids_for_department(current_org.department),
    )


def render_stats_pe(request, page_title, extra_params=None):
    """
    PE ("Pôle emploi") stats shown to relevant members.
    They can view data for their whole departement, not only their agency.
    They cannot view data for other departments than their own.

    `*_main` views are linked directly from the C1 dashboard.
    `*_raw` views are not directly visible on the C1 dashboard but are linked from within their `*_main` counterpart.
    """
    current_org = get_current_org_or_404(request)
    if not utils.can_view_stats_pe(request):
        raise PermissionDenied
    departments = utils.get_stats_pe_departments(request)
    params = {
        mb.DEPARTMENT_FILTER_KEY: [DEPARTMENTS[d] for d in departments],
    }
    if extra_params is None:
        # Do not use mutable default arguments,
        # see https://florimond.dev/en/posts/2018/08/python-mutable-defaults-are-the-source-of-all-evil/
        extra_params = {}
    params.update(extra_params)
    context = {
        "page_title": page_title,
    }
    if current_org.is_dgpe:
        context |= {
            "matomo_custom_url_suffix": "dgpe",
        }
    elif current_org.is_drpe:
        context |= {
            "matomo_custom_url_suffix": f"{format_region_for_matomo(current_org.region)}/drpe",
            "region": current_org.region,
        }
    elif current_org.is_dtpe:
        context |= {
            "matomo_custom_url_suffix": f"{format_region_and_department_for_matomo(current_org.department)}/dtpe",
            "department": current_org.department,
        }
    else:
        context |= {
            "matomo_custom_url_suffix": f"{format_region_and_department_for_matomo(current_org.department)}/agence",
            "department": current_org.department,
        }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_pe_delay_main(request):
    return render_stats_pe(
        request=request,
        page_title="Délai d'entrée en IAE",
        extra_params={
            mb.JOB_APPLICATION_ORIGIN_FILTER_KEY: mb.PE_PRESCRIBER_FILTER_VALUE,
        },
    )


@login_required
def stats_pe_delay_raw(request):
    return render_stats_pe(
        request=request,
        page_title="Données brutes de délai d'entrée en IAE",
        # No additional locked filter is needed for these PE stats.
    )


@login_required
def stats_pe_conversion_main(request):
    return render_stats_pe(
        request=request,
        page_title="Taux de transformation",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: mb.PE_FILTER_VALUE,
        },
    )


@login_required
def stats_pe_conversion_raw(request):
    return render_stats_pe(
        request=request,
        page_title="Données brutes du taux de transformation",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: mb.PE_FILTER_VALUE,
        },
    )


@login_required
def stats_pe_state_main(request):
    return render_stats_pe(
        request=request,
        page_title="Etat des candidatures orientées",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: mb.PE_PRESCRIBER_FILTER_VALUE,
        },
    )


@login_required
def stats_pe_state_raw(request):
    return render_stats_pe(
        request=request,
        page_title="Données brutes de l’état des candidatures orientées",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: mb.PE_PRESCRIBER_FILTER_VALUE,
        },
    )


@login_required
def stats_pe_tension(request):
    return render_stats_pe(
        request=request,
        page_title="Fiches de poste en tension",
        # No additional locked filter is needed for these PE stats.
    )


def render_stats_ph(request, page_title, extra_params=None):
    if not utils.can_view_stats_ph(request):
        raise PermissionDenied

    department = request.current_organization.department
    params = {
        mb.DEPARTMENT_FILTER_KEY: [DEPARTMENTS[department]],
    }
    if extra_params:
        params.update(extra_params)

    context = {
        "page_title": page_title,
        "matomo_custom_url_suffix": f"{format_region_and_department_for_matomo(department)}/agence",
        "department": department,
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_ph_state_main(request):
    return render_stats_ph(
        request=request,
        page_title="Etat des candidatures orientées",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: PrescriberOrganizationKind(request.current_organization.kind).label,
        },
    )


def render_stats_ddets(request, page_title, extra_context, extend_stats_to_whole_region, params=None):
    current_org = get_current_institution_or_404(request)
    department = current_org.department
    department_label = DEPARTMENTS[department]
    region = current_org.region
    context = {
        "page_title": (
            f"{page_title} ({region})" if extend_stats_to_whole_region else f"{page_title} ({department_label})"
        ),
        # Tracking is always based on department even if we show stats for the whole region.
        "department": department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
    }
    if extra_context:
        context.update(extra_context)

    if params is None:
        if extend_stats_to_whole_region:
            params = get_params_for_region(region)
        else:
            params = get_params_for_departement(department)
    return render_stats(request=request, context=context, params=params)


def render_stats_ddets_iae(request, page_title, extra_context=None, extend_stats_to_whole_region=False, params=None):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_ddets_iae(request):
        raise PermissionDenied
    return render_stats_ddets(
        request=request,
        page_title=page_title,
        extra_context=extra_context,
        extend_stats_to_whole_region=extend_stats_to_whole_region,
        params=params,
    )


@login_required
def stats_ddets_iae_auto_prescription(request):
    return render_stats_ddets_iae(request=request, page_title="Focus auto-prescription")


@login_required
def stats_ddets_iae_ph_prescription(request):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_ddets_iae_ph_prescription(request):
        raise PermissionDenied
    return render_stats_ddets_iae(request=request, page_title="Suivi des prescriptions des prescripteurs habilités")


@login_required
def stats_ddets_iae_follow_siae_evaluation(request):
    return render_stats_ddets_iae(request=request, page_title="Suivi du contrôle à posteriori")


@login_required
def stats_ddets_iae_follow_prolongation(request):
    return render_stats_ddets_iae(request=request, page_title="Suivi des demandes de prolongation")


@login_required
def stats_ddets_iae_tension(request):
    return render_stats_ddets_iae(request=request, page_title="SIAE qui peinent à recruter sur le territoire")


@login_required
def stats_ddets_iae_iae(request):
    return render_stats_ddets_iae(request=request, page_title="Données IAE de mon département")


@login_required
def stats_ddets_iae_siae_evaluation(request):
    extra_context = {
        "back_url": reverse("siae_evaluations_views:samples_selection"),
        "show_siae_evaluation_message": True,
    }
    return render_stats_ddets_iae(
        request=request, page_title="Données du contrôle a posteriori", extra_context=extra_context
    )


@login_required
def stats_ddets_iae_hiring(request):
    return render_stats_ddets_iae(
        request=request,
        page_title="Données facilitation de l'embauche de mon département",
    )


@login_required
def stats_ddets_iae_state(request):
    return render_stats_ddets_iae(
        request=request,
        page_title="Suivi des prescriptions des AHI de ma région",
        extend_stats_to_whole_region=True,
    )


@login_required
def stats_ddets_iae_aci(request):
    current_org = get_current_institution_or_404(request)
    if not utils.can_view_stats_ddets_iae_aci(request):
        raise PermissionDenied

    return render_stats_ddets_iae(
        request=request,
        page_title="Suivi du cofinancement des ACI",
        params=get_params_aci_asp_ids_for_department(current_org.department),
    )


def render_stats_ddets_log(request, page_title, extend_stats_to_whole_region):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_ddets_log(request):
        raise PermissionDenied
    return render_stats_ddets(
        request=request,
        page_title=page_title,
        extra_context=None,
        extend_stats_to_whole_region=extend_stats_to_whole_region,
    )


@login_required
def stats_ddets_log_state(request):
    return render_stats_ddets_log(
        request=request,
        page_title="Suivi des prescriptions des AHI de ma région",
        extend_stats_to_whole_region=True,
    )


def render_stats_dreets_iae(request, page_title):
    region = get_stats_dreets_iae_region(request)
    params = get_params_for_region(region)
    context = {
        "page_title": f"{page_title} ({region})",
        "matomo_custom_url_suffix": format_region_for_matomo(region),
        "region": region,
    }
    return render_stats(request=request, context=context, params=params)


@login_required
def stats_dreets_iae_auto_prescription(request):
    return render_stats_dreets_iae(request=request, page_title="Focus auto-prescription")


@login_required
def stats_dreets_iae_ph_prescription(request):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_dreets_iae_ph_prescription(request):
        raise PermissionDenied
    return render_stats_dreets_iae(request=request, page_title="Suivi des prescriptions des prescripteurs habilités")


@login_required
def stats_dreets_iae_follow_siae_evaluation(request):
    return render_stats_dreets_iae(request=request, page_title="Suivi du contrôle à posteriori")


@login_required
def stats_dreets_iae_follow_prolongation(request):
    return render_stats_dreets_iae(request=request, page_title="Suivi des demandes de prolongation")


@login_required
def stats_dreets_iae_tension(request):
    return render_stats_dreets_iae(request=request, page_title="SIAE qui peinent à recruter sur le territoire")


@login_required
def stats_dreets_iae_iae(request):
    return render_stats_dreets_iae(
        request=request,
        page_title="Données IAE de ma région",
    )


@login_required
def stats_dreets_iae_hiring(request):
    return render_stats_dreets_iae(
        request=request,
        page_title="Données facilitation de l'embauche de ma région",
    )


@login_required
def stats_dreets_iae_state(request):
    return render_stats_dreets_iae(
        request=request,
        page_title="Suivi des prescriptions des AHI de ma région",
    )


def render_stats_dgefp(request, page_title, extra_params=None, extra_context=None):
    if extra_context is None:
        # Do not use mutable default arguments,
        # see https://florimond.dev/en/posts/2018/08/python-mutable-defaults-are-the-source-of-all-evil/
        extra_context = {}
    ensure_stats_dgefp_permission(request)
    context = {
        "page_title": page_title,
    }
    context.update(extra_context)
    return render_stats(request=request, context=context, params=extra_params)


@login_required
def stats_dgefp_auto_prescription(request):
    return render_stats_dgefp(
        request=request, page_title="Focus auto-prescription", extra_params=get_params_for_whole_country()
    )


@login_required
def stats_dgefp_follow_siae_evaluation(request):
    return render_stats_dgefp(
        request=request, page_title="Suivi du contrôle à posteriori", extra_params=get_params_for_whole_country()
    )


@login_required
def stats_dgefp_follow_prolongation(request):
    return render_stats_dgefp(
        request=request, page_title="Suivi des demandes de prolongation", extra_params=get_params_for_whole_country()
    )


@login_required
def stats_dgefp_tension(request):
    return render_stats_dgefp(
        request=request,
        page_title="SIAE qui peinent à recruter sur le territoire",
        extra_params=get_params_for_whole_country(),
    )


@login_required
def stats_dgefp_hiring(request):
    return render_stats_dgefp(
        request=request, page_title="Données facilitation de l'embauche", extra_params=get_params_for_whole_country()
    )


@login_required
def stats_dgefp_state(request):
    return render_stats_dgefp(
        request=request,
        page_title="Suivi des prescriptions des AHI de ma région",
        extra_params=get_params_for_whole_country(),
    )


@login_required
def stats_dgefp_iae(request):
    return render_stats_dgefp(
        request=request, page_title="Données des régions", extra_params=get_params_for_whole_country()
    )


@login_required
def stats_dgefp_siae_evaluation(request):
    return render_stats_dgefp(
        request=request,
        page_title="Données (version bêta) du contrôle a posteriori",
        extra_context={"show_siae_evaluation_message": True},
        extra_params=get_params_for_whole_country(),
    )


@login_required
def stats_dgefp_af(request):
    return render_stats_dgefp(request=request, page_title="Annexes financières actives")


@login_required
def stats_dihal_state(request):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_dihal(request):
        raise PermissionDenied
    context = {
        "page_title": "Suivi des prescriptions des AHI",
    }
    return render_stats(request=request, context=context, params=get_params_for_whole_country())


@login_required
def stats_drihl_state(request):
    get_current_institution_or_404(request)
    if not utils.can_view_stats_drihl(request):
        raise PermissionDenied
    context = {
        "page_title": "Suivi des prescriptions des AHI",
    }
    return render_stats(request=request, context=context, params=get_params_for_idf_region())


@login_required
def stats_iae_network_hiring(request):
    current_org = get_current_institution_or_404(request)
    if not utils.can_view_stats_iae_network(request):
        raise PermissionDenied
    context = {
        "page_title": "Données de candidatures des adhérents de mon réseau IAE",
    }
    return render_stats(
        request=request,
        context=context,
        params={mb.IAE_NETWORK_FILTER_KEY: current_org.id},
    )
