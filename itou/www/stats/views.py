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

import datetime
import re

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from itou.analytics.models import StatsDashboardVisit
from itou.common_apps.address.departments import (
    DEPARTMENT_TO_REGION,
    DEPARTMENTS,
    REGIONS,
    format_region_and_department_for_matomo,
    format_region_for_matomo,
)
from itou.companies import models as companies_models
from itou.companies.models import Company
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import UserKind
from itou.utils import constants as global_constants
from itou.utils.apis import metabase as mb
from itou.utils.auth import check_request
from itou.www.stats import utils


DGEFP_SHOWROOM_DEPARTMENT = "69"
DGEFP_SHOWROOM_CONVERGENCE_REGION = "Île-de-France"
DGEFP_SHOWROOM_IAE_NETWORK_NAME = "Unai"


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


def render_stats(
    *, request, context, params=None, template_name="stats/stats.html", view_name=None, show_tally=settings.TALLY_URL
):
    if params is None:
        params = {}

    view_name = view_name or mb.get_view_name(request)
    metabase_dashboard = mb.METABASE_DASHBOARDS[view_name]
    dashboard_id = metabase_dashboard["dashboard_id"]

    base_context = {
        "back_url": None,
        "iframeurl": mb.metabase_embedded_url(dashboard_id=dashboard_id, params=params),
        "is_stats_public": False,
        "show_siae_evaluation_message": False,
        "stats_base_url": settings.METABASE_SITE_URL,
        "tally_popup_form_id": metabase_dashboard.get("tally_popup_form_id") if show_tally else None,
        "tally_embed_form_id": metabase_dashboard.get("tally_embed_form_id") if show_tally else None,
        "PILOTAGE_HELP_CENTER_URL": global_constants.PILOTAGE_HELP_CENTER_URL,
        "tally_suspension_form": (
            f"https://tally.so/r/wkOxRR?URLTB={dashboard_id}" if dashboard_id in mb.SUSPENDED_DASHBOARD_IDS else None
        ),
        "tally_hidden_fields": {},
    }

    # Key value pairs in context override preexisting pairs in base_context.
    base_context.update(context)
    if request.user.is_authenticated and request.user.is_employer:
        base_context.setdefault("pilotage_webinar_banners", [])
        base_context["pilotage_webinar_banners"].append(
            {
                "title": "Enquête SIAE : construisons ensemble les outils de demain",
                "description": "Partagez votre expérience sur vos défis quotidiens et vos pratiques de pilotage. Aidez-nous à développer de meilleurs outils, adaptés à vos besoins.",  # noqa: E501
                "call_to_action": "Participer à l'enquête",
                "url": "https://etudes.inclusion.gouv.fr/siae-2025",
                "is_displayable": lambda: timezone.localdate() <= datetime.date(2025, 7, 18),
            }
        )
    if "pilotage_webinar_banners" not in base_context:
        base_context["pilotage_webinar_banners"] = [
            {
                "title": "Des questions sur l’utilisation des tableaux de bord ?",
                "description": "Nous y répondons lors d’un webinaire questions / réponses animé chaque mois.",  # noqa: E501
                "call_to_action": "Je m’inscris",
                "url": "https://app.livestorm.co/itou/le-pilotage-de-linclusion-professionnels-de-liae-questions-reponses-sur-les-tableaux-de-bord-1",
                "is_displayable": lambda: settings.PILOTAGE_SHOW_STATS_WEBINAR,
            }
        ]
    base_context["pilotage_webinar_banners"] = [
        banner for banner in base_context["pilotage_webinar_banners"] if banner["is_displayable"]()
    ]

    matomo_custom_url = request.resolver_match.route  # e.g. "stats/pe/delay/main"
    if suffix := base_context.pop("matomo_custom_url_suffix", None):
        # E.g. `/stats/ddets/iae/Provence-Alpes-Cote-d-Azur/04---Alpes-de-Haute-Provence`
        matomo_custom_url += f"/{suffix}"
    base_context["matomo_custom_url"] = matomo_custom_url

    if request.user.is_authenticated and metabase_dashboard:
        extra_data = {}
        if request.user.is_employer:
            extra_data["current_company_id"] = request.current_organization.pk
        elif request.user.is_prescriber and request.current_organization:
            extra_data["current_prescriber_organization_id"] = request.current_organization.pk
        elif request.user.is_labor_inspector:
            extra_data["current_institution_id"] = request.current_organization.pk
        user_kind = request.user.kind
        department = base_context.get("department")
        region = DEPARTMENT_TO_REGION[department] if department else base_context.get("region")
        dashboard_id = metabase_dashboard.get("dashboard_id")
        StatsDashboardVisit.objects.create(
            dashboard_id=dashboard_id,
            dashboard_name=view_name,
            department=department,
            region=region,
            user_kind=user_kind,
            user_id=request.user.pk,
            **extra_data,
        )

    return render(request, template_name, base_context)


@login_not_required
def stats_public(request):
    """
    Public basic stats (signed and embedded version)
    """
    context = {
        "page_title": "Statistiques",
        "is_stats_public": True,
    }
    return render_stats(request=request, context=context)


def stats_redirect(request, dashboard_name):
    match request.user.kind:
        case UserKind.LABOR_INSPECTOR:
            normalized_organization_kind = request.current_organization.kind.lower().replace(" ", "_")
        case _:
            return HttpResponseNotFound()

    return HttpResponseRedirect(reverse(f"stats:stats_{normalized_organization_kind}_{dashboard_name}"))


@check_request(utils.can_view_stats_siae_etp)
def stats_siae_etp(request):
    """
    SIAE stats shown to their own members.
    They can only view data for their own SIAE.
    These stats are about ETP data from the ASP.
    """
    context = {
        "page_title": "Suivi des effectifs annuels et mensuels (ETP) de ma ou mes structures",
        "department": request.current_organization.department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(request.current_organization.department),
    }
    return render_stats(
        request=request,
        context=context,
        params={
            mb.ASP_SIAE_FILTER_KEY_FLAVOR3: [
                str(membership.company.convention.asp_id)
                for membership in request.user.active_or_in_grace_period_company_memberships()
                if membership.is_admin and membership.company.convention is not None
            ]
        },
    )


def render_stats_siae(request, page_title, *, filter_param=mb.C1_SIAE_FILTER_KEY):
    """
    SIAE stats shown only to their own members.
    Employers can see stats for all their SIAEs at once, not just the one currently being worked on.
    These stats are built directly from C1 data.
    """
    context = {
        "page_title": page_title,
        "department": request.current_organization.department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(request.current_organization.department),
    }
    match filter_param:
        case mb.C1_SIAE_FILTER_KEY:
            params = {
                mb.C1_SIAE_FILTER_KEY: [
                    str(membership.company_id)
                    for membership in request.user.active_or_in_grace_period_company_memberships()
                ]
            }
        case mb.ASP_SIAE_FILTER_KEY_FLAVOR3:
            params = {
                mb.ASP_SIAE_FILTER_KEY_FLAVOR3: [
                    org.convention.asp_id for org in request.organizations if org.convention is not None
                ],
            }

    return render_stats(
        request=request,
        context=context,
        params=params,
    )


@check_request(utils.can_view_stats_siae)
def stats_siae_hiring(request):
    return render_stats_siae(request=request, page_title="Analyse des candidatures reçues et de leur traitement")


@check_request(utils.can_view_stats_siae)
def stats_siae_auto_prescription(request):
    return render_stats_siae(
        request=request, page_title="Suivi de l’activité d’auto-prescription et du contrôle à posteriori"
    )


@check_request(utils.can_view_stats_siae)
def stats_siae_orga_etp(request):
    """
    SIAE stats shown to their own members.
    They can only view data for their own SIAE.
    These stats are about ETP data from the ASP.
    """
    return render_stats_siae(
        request=request,
        page_title="Suivi des effectifs annuels et mensuels (ETP)",
        filter_param=mb.ASP_SIAE_FILTER_KEY_FLAVOR3,
    )


@check_request(utils.can_view_stats_siae)
def stats_siae_beneficiaries(request):
    return render_stats_siae(
        request=request,
        page_title="Suivi des bénéficiaires, taux d’encadrement et présence en emploi",
        filter_param=mb.ASP_SIAE_FILTER_KEY_FLAVOR3,
    )


def render_stats_cd(request, page_title, *, params=None, extra_context=None):
    """
    CD ("Conseil Départemental") stats shown to relevant members.
    They can only view data for their own departement.
    """
    department = request.current_organization.department
    params = get_params_for_departement(department) if params is None else params
    context = {
        "page_title": f"{page_title} de mon département : {DEPARTMENTS[department]}",
        "department": department,
        "matomo_custom_url_suffix": format_region_and_department_for_matomo(department),
        "tally_hidden_fields": {"type_prescripteur": request.current_organization.kind},
    }
    if extra_context:
        context.update(extra_context)
    return render_stats(request=request, context=context, params=params)


@check_request(utils.can_view_stats_cd)
def stats_cd_iae(request):
    return render_stats_cd(request=request, page_title="Données IAE")


@check_request(utils.can_view_stats_cd)
def stats_cd_hiring(request):
    return render_stats_cd(request=request, page_title="Analyse des candidatures reçues et de leur traitement")


@check_request(utils.can_view_stats_cd)
def stats_cd_brsa(request):
    return render_stats_cd(request=request, page_title="Analyse des prescriptions pour les publics ARSA")


@check_request(utils.can_view_stats_cd)
def stats_cd_orga_etp(request):
    return render_stats_cd(
        request=request,
        page_title="Suivi des effectifs annuels et mensuels (ETP)",
    )


@check_request(utils.can_view_stats_cd)
def stats_cd_beneficiaries(request):
    return render_stats_cd(
        request=request, page_title="Suivi des bénéficiaires, taux d’encadrement et présence en emploi"
    )


def render_stats_ft(request, page_title, extra_params=None, *, with_region_param=False, with_department_name=True):
    """
    FT ("France Travail") stats shown to relevant members.
    They can view data for their whole departement, not only their agency.
    They cannot view data for other departments than their own.

    `*_main` views are linked directly from the C1 dashboard.
    `*_raw` views are not directly visible on the C1 dashboard but are linked from within their `*_main` counterpart.
    """
    departments = utils.get_stats_ft_departments(request.current_organization)
    params = {
        mb.DEPARTMENT_FILTER_KEY: [DEPARTMENTS[d] for d in departments] if with_department_name else departments,
    }
    if with_region_param:
        regions = {DEPARTMENT_TO_REGION[d] for d in departments}
        params[mb.REGION_FILTER_KEY] = list(regions)
    if extra_params is None:
        # Do not use mutable default arguments,
        # see https://florimond.dev/en/posts/2018/08/python-mutable-defaults-are-the-source-of-all-evil/
        extra_params = {}
    params.update(extra_params)
    context = {
        "page_title": page_title,
        "tally_hidden_fields": {"type_prescripteur": request.current_organization.kind},
    }
    if request.current_organization.is_dgft:
        context |= {
            "matomo_custom_url_suffix": "dgpe",
        }
    elif request.current_organization.is_drft:
        context |= {
            "matomo_custom_url_suffix": f"{format_region_for_matomo(request.current_organization.region)}/drpe",
            "region": request.current_organization.region,
        }
    elif request.current_organization.is_dtft:
        matomo_base = format_region_and_department_for_matomo(request.current_organization.department)
        context |= {
            "matomo_custom_url_suffix": f"{matomo_base}/dtpe",
            "department": request.current_organization.department,
        }
    else:
        matomo_base = format_region_and_department_for_matomo(request.current_organization.department)
        context |= {
            "matomo_custom_url_suffix": f"{matomo_base}/agence",
            "department": request.current_organization.department,
        }
    return render_stats(request=request, context=context, params=params)


@check_request(utils.can_view_stats_ft)
def stats_ft_conversion_main(request):
    return render_stats_ft(
        request=request,
        page_title="Analyse des parcours des candidats diagnostiqués",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: mb.FT_FILTER_VALUE,
        },
        with_department_name=False,
    )


@check_request(utils.can_view_stats_ft)
def stats_ft_state_main(request):
    return render_stats_ft(
        request=request,
        page_title="Analyse des candidatures émises et de leur traitement",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: mb.FT_PRESCRIBER_FILTER_VALUE,
        },
        with_department_name=False,
    )


@check_request(utils.can_view_stats_ft)
def stats_ft_beneficiaries(request):
    return render_stats_ft(
        request=request,
        page_title="Suivi des bénéficiaires, taux d’encadrement et présence en emploi",
        with_region_param=True,
    )


@check_request(utils.can_view_stats_ft)
def stats_ft_hiring(request):
    return render_stats_ft(
        request=request,
        page_title="Analyse de l'ensemble des candidatures reçues par les SIAE",
        # The Metabase filter is not "locked" so it's not required,
        # and sending the parameter for DGFT will break because of the max URL length
        with_region_param=not request.current_organization.is_dgft,
    )


def render_stats_ph(request, page_title, *, extra_params=None, extra_context=None):
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
    if extra_context:
        context.update(extra_context)
    return render_stats(request=request, context=context, params=params)


@check_request(utils.can_view_stats_ph_whitelisted)
def stats_ph_state_main(request):
    allowed_org_pks = list(
        PrescriberOrganization.objects.filter(
            kind=request.current_organization.kind,
            department=request.current_organization.department,
        ).values_list("pk", flat=True)
    )

    extra_context = {"tally_hidden_fields": {"type_prescripteur": request.current_organization.kind}}
    if request.current_organization.kind == PrescriberOrganizationKind.PLIE:
        extra_context["pilotage_webinar_banners"] = [
            {
                "title": "Découvrez votre tableau de bord",
                "description": "PLIE, apprenez à manipuler les données disponibles dans ce tableau de bord et à les utiliser dans le cadre de vos missions en consultant le replay du webinaire que nous avons conçu et animé spécialement pour vous.",  # noqa: E501
                "call_to_action": "Je consulte le replay",
                "url": "https://aide.pilotage.inclusion.beta.gouv.fr/hc/fr/articles/34596775109905--AVRIL-MAI-2025-Webinaire-d%C3%A9couverte-pour-les-PLIE",  # noqa: E501
                "is_displayable": lambda: timezone.localdate() <= datetime.date(2025, 8, 31),
            }
        ]
    return render_stats_ph(
        request=request,
        page_title="Analyse des candidatures émises et de leur traitement",
        extra_params={
            mb.PRESCRIBER_FILTER_KEY: PrescriberOrganizationKind(request.current_organization.kind).label,
            mb.C1_PRESCRIBER_ORG_FILTER_KEY: allowed_org_pks,
        },
        extra_context=extra_context,
    )


@check_request(utils.can_view_stats_ph)
def stats_ph_beneficiaries(request):
    return render_stats_ph(
        request=request,
        page_title="Suivi des bénéficiaires, taux d’encadrement et présence en emploi",
        extra_params=get_params_for_departement(request.current_organization.department),
        extra_context={"tally_hidden_fields": {"type_prescripteur": request.current_organization.kind}},
    )


def render_stats_ddets(request, *, page_title, extra_context=None, extend_stats_to_whole_region=False):
    department = request.current_organization.department
    department_label = DEPARTMENTS[department]
    region = request.current_organization.region
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

    params = get_params_for_region(region) if extend_stats_to_whole_region else get_params_for_departement(department)
    return render_stats(request=request, context=context, params=params)


@check_request(utils.can_view_stats_ddets_iae)
def stats_ddets_iae_auto_prescription(request):
    return render_stats_ddets(request=request, page_title="Analyse des auto-prescriptions et de leur contrôle")


@check_request(utils.can_view_stats_ddets_iae)
def stats_ddets_iae_ph_prescription(request):
    return render_stats_ddets(request=request, page_title="Analyse des candidatures émises et de leur traitement")


@check_request(utils.can_view_stats_ddets_iae)
def stats_ddets_iae_siae_evaluation(request):
    extra_context = {
        "back_url": reverse("siae_evaluations_views:samples_selection"),
        "show_siae_evaluation_message": True,
    }
    return render_stats_ddets(
        request=request, page_title="Données du contrôle a posteriori", extra_context=extra_context
    )


@check_request(utils.can_view_stats_ddets_iae)
def stats_ddets_iae_hiring(request):
    return render_stats_ddets(
        request=request,
        page_title="Analyse des candidatures reçues et de leur traitement",
    )


@check_request(utils.can_view_stats_ddets_iae)
def stats_ddets_iae_state(request):
    return render_stats_ddets(
        request=request,
        page_title="Analyse des candidatures émises par les acteurs AHI",
        extend_stats_to_whole_region=True,
    )


@check_request(utils.can_view_stats_ddets_iae)
def stats_ddets_iae_orga_etp(request):
    return render_stats_ddets(
        request=request,
        page_title="Suivi des effectifs annuels et mensuels (ETP)",
    )


@check_request(utils.can_view_stats_ddets_log)
def stats_ddets_log_state(request):
    return render_stats_ddets(
        request=request,
        page_title="Suivi des prescriptions des AHI de ma région",
        extend_stats_to_whole_region=True,
    )


def render_stats_dreets_iae(request, page_title, *, extra_context=None):
    region = request.current_organization.region
    context = {
        "page_title": f"{page_title} ({region})",
        "matomo_custom_url_suffix": format_region_for_matomo(region),
        "region": region,
    }
    context.update(extra_context or {})
    return render_stats(request=request, context=context, params=get_params_for_region(region))


@check_request(utils.can_view_stats_dreets_iae)
def stats_dreets_iae_auto_prescription(request):
    return render_stats_dreets_iae(request=request, page_title="Analyse des auto-prescriptions et de leur contrôle")


@check_request(utils.can_view_stats_dreets_iae)
def stats_dreets_iae_ph_prescription(request):
    return render_stats_dreets_iae(request=request, page_title="Analyse des candidatures émises et de leur traitement")


@check_request(utils.can_view_stats_dreets_iae)
def stats_dreets_iae_hiring(request):
    return render_stats_dreets_iae(
        request=request,
        page_title="Analyse des candidatures reçues et de leur traitement",
    )


@check_request(utils.can_view_stats_dreets_iae)
def stats_dreets_iae_state(request):
    return render_stats_dreets_iae(
        request=request,
        page_title="Analyse des candidatures émises par les acteurs AHI",
    )


@check_request(utils.can_view_stats_dreets_iae)
def stats_dreets_iae_orga_etp(request):
    return render_stats_dreets_iae(
        request=request,
        page_title="Suivi des effectifs annuels et mensuels (ETP)",
    )


def render_stats_dgefp_iae(request, page_title, extra_params=None, extra_context=None):
    extra_context = extra_context or {}

    return render_stats(
        request=request,
        context={
            "page_title": page_title,
            **extra_context,
        },
        params=extra_params,
    )


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_auto_prescription(request):
    return render_stats_dgefp_iae(request=request, page_title="Focus auto-prescription")


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_follow_siae_evaluation(request):
    return render_stats_dgefp_iae(request=request, page_title="Suivi du contrôle à posteriori")


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_hiring(request):
    return render_stats_dgefp_iae(request=request, page_title="Données facilitation de l'embauche")


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_state(request):
    return render_stats_dgefp_iae(
        request=request,
        page_title="Suivi des prescriptions des AHI de ma région",
    )


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_ph_prescription(request):
    return render_stats_dgefp_iae(
        request=request,
        page_title="Suivi des prescriptions des prescripteurs habilités",
    )


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_siae_evaluation(request):
    return render_stats_dgefp_iae(
        request=request,
        page_title="Données (version bêta) du contrôle a posteriori",
        extra_context={"show_siae_evaluation_message": True},
    )


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_orga_etp(request):
    return render_stats_dgefp_iae(
        request=request,
        page_title="Suivi des effectifs annuels et mensuels en ETP",
    )


@check_request(utils.can_view_stats_dgefp_iae)
def stats_dgefp_iae_showroom(request, dashboard_full_name):
    if f"stats_{dashboard_full_name}" not in mb.METABASE_DASHBOARDS:
        return HttpResponseNotFound()

    [kind, name] = re.match(r"(cd|convergence|ddets_iae|ft|iae_network|ph|siae)_(\w+)", dashboard_full_name).groups()
    if kind == "cd":
        params = get_params_for_departement(DGEFP_SHOWROOM_DEPARTMENT)
    if kind == "ddets_iae":
        params = get_params_for_departement(DGEFP_SHOWROOM_DEPARTMENT)
    if kind == "convergence":
        params = get_params_for_region(DGEFP_SHOWROOM_CONVERGENCE_REGION)
    elif kind == "ft":
        params = {
            # FIXME: **get_params_for_departement(DGEFP_SHOWROOM_DEPARTMENT),
            mb.DEPARTMENT_FILTER_KEY: DEPARTMENTS[DGEFP_SHOWROOM_DEPARTMENT],
            mb.PRESCRIBER_FILTER_KEY: mb.FT_PRESCRIBER_FILTER_VALUE,
        }
    elif kind == "iae_network":
        params = {
            mb.IAE_NETWORK_FILTER_KEY: Institution.objects.filter(
                kind=InstitutionKind.IAE_NETWORK, name=DGEFP_SHOWROOM_IAE_NETWORK_NAME
            )
            .values_list("pk", flat=True)
            .get()
        }
    elif kind == "ph":
        match name:
            case "state_main":
                organization_pks = set()
                organization_labels = set()
                for organization in (
                    PrescriberOrganization.objects.with_has_active_members()
                    # Only authorized prescriber organizations
                    .filter(authorization_status=PrescriberAuthorizationStatus.VALIDATED)
                    # Mimic `can_view_stats_ph()`
                    .filter(has_active_members=True, kind__in=utils.STATS_PH_ORGANISATION_KIND_WHITELIST)
                    # Limit to the selected department
                    .filter(department=DGEFP_SHOWROOM_DEPARTMENT)
                    .values_list("pk", "kind", named=True)
                ):
                    organization_pks.add(organization.pk)
                    organization_labels.add(PrescriberOrganizationKind(organization.kind).label)
                params = {
                    mb.PRESCRIBER_FILTER_KEY: list(organization_labels),
                    mb.C1_PRESCRIBER_ORG_FILTER_KEY: list(organization_pks),
                }
            case "beneficiaries":
                params = get_params_for_departement(DGEFP_SHOWROOM_DEPARTMENT)
    elif kind == "siae":
        match name:
            case "orga_etp" | "beneficiaries":
                param_name, value_field = mb.ASP_SIAE_FILTER_KEY_FLAVOR3, "convention__asp_id"
            case _:
                param_name, value_field = mb.C1_SIAE_FILTER_KEY, "pk"
        params = {
            param_name: list(
                set(
                    Company.objects.active_or_in_grace_period()
                    .with_has_active_members()
                    .filter(has_active_members=True, department=DGEFP_SHOWROOM_DEPARTMENT)
                    .values_list(value_field, flat=True)
                )
            ),
        }

    return render_stats(
        request=request,
        context={"department": None, "region": None},  # Force national level
        params=params,
        view_name=f"stats_{dashboard_full_name}",
        show_tally=False,
    )


@check_request(utils.can_view_stats_dihal)
def stats_dihal_state(request):
    context = {
        "page_title": "Suivi des prescriptions des AHI",
    }
    return render_stats(request=request, context=context)


@check_request(utils.can_view_stats_drihl)
def stats_drihl_state(request):
    context = {
        "page_title": "Suivi des prescriptions des AHI",
    }
    return render_stats(request=request, context=context, params=get_params_for_region("Île-de-France"))


@check_request(utils.can_view_stats_iae_network)
def stats_iae_network_hiring(request):
    context = {
        "page_title": "Données de candidatures des adhérents de mon réseau IAE",
    }
    return render_stats(
        request=request,
        context=context,
        params={mb.IAE_NETWORK_FILTER_KEY: request.current_organization.id},
    )


@check_request(utils.can_view_stats_convergence)
def stats_convergence_prescription(request):
    return render_stats(
        request=request,
        context={
            "page_title": "Prescriptions et parcours",
        },
    )


@check_request(utils.can_view_stats_convergence)
def stats_convergence_job_application(request):
    return render_stats(
        request=request,
        context={
            "page_title": "Traitement et résultats des candidatures",
        },
    )


@check_request(utils.can_view_stats_staff)
def stats_staff_service_indicators(request):
    """Indicator statistics for Les Emplois staff"""
    return render_stats(request=request, context={"page_title": "Indicateurs à suivre"})
