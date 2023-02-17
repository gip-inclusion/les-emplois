import time

import jwt
from django.conf import settings


ASP_SIAE_FILTER_KEY = "identifiant_de_la_structure"
C1_SIAE_FILTER_KEY = "identifiant_de_la_structure_(c1)"
DEPARTMENT_FILTER_KEY = "d%C3%A9partement"
REGION_FILTER_KEY = "r%C3%A9gion"

METABASE_DASHBOARDS = {
    #
    # Public stats.
    #
    "stats_public": {
        "dashboard_id": 119,
    },
    #
    # Temporary items to easily test and debug ongoing tally popup issues.
    #
    "stats_test1": {
        "dashboard_id": 119,
    },
    "stats_test2": {
        "dashboard_id": 119,
    },
    #
    # Employer stats.
    #
    "stats_siae_etp": {
        "dashboard_id": 128,
    },
    "stats_siae_hiring": {
        "dashboard_id": 185,
        "tally_form_id": "waQPkB",
    },
    #
    # Prescriber stats - CD.
    #
    "stats_cd": {
        "dashboard_id": 118,
    },
    #
    # Prescriber stats - PE.
    #
    "stats_pe_delay_main": {
        "dashboard_id": 168,
        "tally_form_id": "3lb9XW",
    },
    "stats_pe_delay_raw": {
        "dashboard_id": 180,
    },
    "stats_pe_conversion_main": {
        "dashboard_id": 169,
        "tally_form_id": "mODeK8",
    },
    "stats_pe_conversion_raw": {
        "dashboard_id": 182,
    },
    "stats_pe_state_main": {
        "dashboard_id": 149,
        "tally_form_id": "mRG61J",
    },
    "stats_pe_state_raw": {
        "dashboard_id": 183,
    },
    "stats_pe_tension": {
        "dashboard_id": 162,
        "tally_form_id": "wobaYV",
    },
    #
    # Institution stats - DDETS - department level.
    #
    "stats_ddets_auto_prescription": {
        "dashboard_id": 267,
    },
    "stats_ddets_follow_diagnosis_control": {
        "dashboard_id": 265,
    },
    "stats_ddets_iae": {
        "dashboard_id": 117,
    },
    "stats_ddets_diagnosis_control": {
        "dashboard_id": 144,
    },
    "stats_ddets_hiring": {
        "dashboard_id": 160,
        "tally_form_id": "mVLBXv",
    },
    #
    # Institution stats - DREETS - region level.
    #
    "stats_dreets_auto_prescription": {
        "dashboard_id": 267,
    },
    "stats_dreets_follow_diagnosis_control": {
        "dashboard_id": 265,
    },
    "stats_dreets_iae": {
        "dashboard_id": 117,
    },
    "stats_dreets_hiring": {
        "dashboard_id": 160,
        "tally_form_id": "mVLBXv",
    },
    #
    # Institution stats - DGEFP - nation level.
    #
    "stats_dgefp_auto_prescription": {
        "dashboard_id": 267,
    },
    "stats_dgefp_follow_diagnosis_control": {
        "dashboard_id": 265,
    },
    "stats_dgefp_iae": {
        "dashboard_id": 117,
    },
    "stats_dgefp_diagnosis_control": {
        "dashboard_id": 144,
    },
    "stats_dgefp_af": {
        "dashboard_id": 142,
    },
    #
    # Institution stats - DIHAL - nation level.
    #
    "stats_dihal_state": {
        "dashboard_id": 235,
    },
}


# Metabase private / signed URLs
# See:
# * https://www.metabase.com/docs/latest/enterprise-guide/full-app-embedding.html
# * https://github.com/jpadilla/pyjwt
# * https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py
def _get_token(payload):
    return jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")


def get_view_name(request):
    full_view_name = request.resolver_match.view_name  # e.g. "stats:stats_public"
    view_name = full_view_name.split(":")[-1]  # e.g. "stats_public"
    return view_name


def metabase_embedded_url(request=None, dashboard_id=None, params={}, with_title=False):
    """
    Creates an embed/signed URL for embedded Metabase dashboards:
    * expiration delay of token set at 10 minutes, kept short on purpose due to the fact that during this short time
      the user can share the iframe URL to non authorized third parties
    * do not display title of the dashboard in the iframe
    * optional parameters typically for locked filters (e.g. allow viewing data of one departement only)
    """
    if dashboard_id is None:
        view_name = get_view_name(request)
        metabase_dashboard = METABASE_DASHBOARDS.get(view_name)
        dashboard_id = metabase_dashboard["dashboard_id"] if metabase_dashboard else None

    payload = {"resource": {"dashboard": dashboard_id}, "params": params, "exp": round(time.time()) + (10 * 60)}
    is_titled = "true" if with_title else "false"
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload) + f"#titled={is_titled}"
