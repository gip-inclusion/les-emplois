import time

import jwt
from django.conf import settings


ASP_SIAE_FILTER_KEY_FLAVOR1 = "identifiant_de_la_structure"
ASP_SIAE_FILTER_KEY_FLAVOR2 = "id_asp_de_la_siae"
ASP_SIAE_FILTER_KEY_FLAVOR3 = "id_asp_siae"
C1_SIAE_FILTER_KEY = "identifiant_de_la_structure_(c1)"
IAE_NETWORK_FILTER_KEY = "id_r%C3%A9seau"
DEPARTMENT_FILTER_KEY = "d%C3%A9partement"
REGION_FILTER_KEY = "r%C3%A9gion"
PRESCRIBER_FILTER_KEY = "prescripteur"
JOB_APPLICATION_ORIGIN_FILTER_KEY = "origine_candidature"
PE_PRESCRIBER_FILTER_VALUE = "France Travail"
PE_FILTER_VALUE = "France Travail"

METABASE_DASHBOARDS = {
    #
    # Public stats.
    #
    "stats_public": {
        "dashboard_id": 236,
    },
    #
    # Employer stats.
    #
    "stats_siae_aci": {
        "dashboard_id": 327,
    },
    "stats_siae_etp": {
        "dashboard_id": 440,
    },
    "stats_siae_hiring": {
        "dashboard_id": 185,
        "tally_popup_form_id": "waQPkB",
        "tally_embed_form_id": "nG6J62",
    },
    "stats_siae_auto_prescription": {
        "dashboard_id": 295,
    },
    "stats_siae_follow_siae_evaluation": {
        "dashboard_id": 298,
    },
    "stats_siae_hiring_report": {
        "dashboard_id": 394,
        "tally_popup_form_id": "wb7lR1",
        "tally_embed_form_id": "wkyYjo",
    },
    #
    # Prescriber stats - CD.
    #
    "stats_cd_iae": {
        "dashboard_id": 118,
        "tally_popup_form_id": "npD4g8",
        "tally_embed_form_id": "m6ZrqY",
    },
    "stats_cd_hiring": {
        "dashboard_id": 346,
    },
    "stats_cd_brsa": {
        "dashboard_id": 330,
    },
    "stats_cd_aci": {
        "dashboard_id": 327,
    },
    #
    # Prescriber stats - PE.
    #
    "stats_pe_delay_main": {
        "dashboard_id": 168,
        "tally_popup_form_id": "3lb9XW",
        "tally_embed_form_id": "meM7DE",
    },
    "stats_pe_delay_raw": {
        "dashboard_id": 180,
    },
    "stats_pe_conversion_main": {
        "dashboard_id": 169,
        "tally_popup_form_id": "mODeK8",
        "tally_embed_form_id": "3xrPjJ",
    },
    "stats_pe_conversion_raw": {
        "dashboard_id": 182,
    },
    "stats_pe_state_main": {
        "dashboard_id": 149,
        "tally_popup_form_id": "mRG61J",
        "tally_embed_form_id": "3qLKad",
    },
    "stats_pe_state_raw": {
        "dashboard_id": 183,
    },
    "stats_pe_tension": {
        "dashboard_id": 162,
        "tally_popup_form_id": "wobaYV",
        "tally_embed_form_id": "3EKJ5q",
    },
    #
    # Authorized Prescribers' stats
    #
    "stats_ph_state_main": {
        "dashboard_id": 149,
    },
    #
    # Institution stats - DDETS IAE - department level.
    #
    "stats_ddets_iae_auto_prescription": {
        "dashboard_id": 267,
        "tally_popup_form_id": "3qLpE2",
        "tally_embed_form_id": "nG6gBj",
    },
    "stats_ddets_iae_ph_prescription": {
        "dashboard_id": 289,
        "tally_popup_form_id": "wbWKEo",
        "tally_embed_form_id": "wvPEvQ",
    },
    "stats_ddets_iae_follow_siae_evaluation": {
        "dashboard_id": 265,
        "tally_popup_form_id": "w2XZxV",
        "tally_embed_form_id": "n9Ba6G",
    },
    "stats_ddets_iae_follow_prolongation": {
        "dashboard_id": 357,
    },
    "stats_ddets_iae_tension": {
        "dashboard_id": 389,
    },
    "stats_ddets_iae_iae": {
        "dashboard_id": 117,
    },
    "stats_ddets_iae_siae_evaluation": {
        "dashboard_id": 144,
    },
    "stats_ddets_iae_hiring": {
        "dashboard_id": 160,
        "tally_popup_form_id": "mVLBXv",
        "tally_embed_form_id": "nPpXpQ",
    },
    "stats_ddets_iae_state": {
        "dashboard_id": 310,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    "stats_ddets_iae_aci": {
        "dashboard_id": 327,
    },
    #
    # Institution stats - DDETS LOG - department level.
    #
    "stats_ddets_log_state": {
        "dashboard_id": 310,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    #
    # Institution stats - DREETS IAE - region level.
    #
    "stats_dreets_iae_auto_prescription": {
        "dashboard_id": 267,
        "tally_popup_form_id": "3qLpE2",
        "tally_embed_form_id": "nG6gBj",
    },
    "stats_dreets_iae_ph_prescription": {
        "dashboard_id": 289,
        "tally_popup_form_id": "wbWKEo",
        "tally_embed_form_id": "wvPEvQ",
    },
    "stats_dreets_iae_follow_siae_evaluation": {
        "dashboard_id": 265,
        "tally_popup_form_id": "w2XZxV",
        "tally_embed_form_id": "n9Ba6G",
    },
    "stats_dreets_iae_follow_prolongation": {
        "dashboard_id": 357,
    },
    "stats_dreets_iae_tension": {
        "dashboard_id": 389,
    },
    "stats_dreets_iae_iae": {
        "dashboard_id": 117,
    },
    "stats_dreets_iae_hiring": {
        "dashboard_id": 160,
        "tally_popup_form_id": "mVLBXv",
        "tally_embed_form_id": "nPpXpQ",
    },
    "stats_dreets_iae_state": {
        "dashboard_id": 310,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    #
    # Institution stats - DRIHL - region level - IDF only.
    #
    "stats_drihl_state": {
        "dashboard_id": 310,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    #
    # Institution stats - DGEFP - nation level.
    #
    "stats_dgefp_auto_prescription": {
        "dashboard_id": 267,
        "tally_popup_form_id": "3qLpE2",
        "tally_embed_form_id": "nG6gBj",
    },
    "stats_dgefp_follow_siae_evaluation": {
        "dashboard_id": 265,
        "tally_popup_form_id": "w2XZxV",
        "tally_embed_form_id": "n9Ba6G",
    },
    "stats_dgefp_follow_prolongation": {
        "dashboard_id": 357,
    },
    "stats_dgefp_tension": {
        "dashboard_id": 389,
    },
    "stats_dgefp_hiring": {
        "dashboard_id": 160,
    },
    "stats_dgefp_state": {
        "dashboard_id": 310,
    },
    "stats_dgefp_iae": {
        "dashboard_id": 117,
    },
    "stats_dgefp_siae_evaluation": {
        "dashboard_id": 144,
    },
    "stats_dgefp_af": {
        "dashboard_id": 142,
    },
    #
    # Institution stats - DIHAL - nation level.
    #
    "stats_dihal_state": {
        "dashboard_id": 310,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    #
    # Institution stats - IAE Network - nation level.
    #
    "stats_iae_network_hiring": {
        "dashboard_id": 301,
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


def metabase_embedded_url(request=None, dashboard_id=None, params=None, with_title=False):
    """
    Creates an embed/signed URL for embedded Metabase dashboards:
    * expiration delay of token set at 10 minutes, kept short on purpose due to the fact that during this short time
      the user can share the iframe URL to non authorized third parties
    * do not display title of the dashboard in the iframe
    * optional parameters typically for locked filters (e.g. allow viewing data of one departement only)
    """
    if params is None:
        params = {}
    if dashboard_id is None:
        view_name = get_view_name(request)
        metabase_dashboard = METABASE_DASHBOARDS.get(view_name)
        dashboard_id = metabase_dashboard["dashboard_id"] if metabase_dashboard else None

    payload = {"resource": {"dashboard": dashboard_id}, "params": params, "exp": round(time.time()) + (10 * 60)}
    is_titled = "true" if with_title else "false"
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload) + f"#titled={is_titled}"
