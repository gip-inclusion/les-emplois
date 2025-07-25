import copy
import datetime
import json
from urllib.parse import urljoin

import httpx
import jwt
from django.conf import settings
from django.utils import timezone


ASP_SIAE_FILTER_KEY_FLAVOR1 = "identifiant_de_la_structure"
ASP_SIAE_FILTER_KEY_FLAVOR2 = "id_asp_de_la_siae"
ASP_SIAE_FILTER_KEY_FLAVOR3 = "id_asp_siae"
C1_SIAE_FILTER_KEY = "identifiant_de_la_structure_(c1)"
C1_PRESCRIBER_ORG_FILTER_KEY = "id_prescripteur"
IAE_NETWORK_FILTER_KEY = "id_r%C3%A9seau"
DEPARTMENT_FILTER_KEY = "d%C3%A9partement"
REGION_FILTER_KEY = "r%C3%A9gion"
PRESCRIBER_FILTER_KEY = "prescripteur"
JOB_APPLICATION_ORIGIN_FILTER_KEY = "origine_candidature"
FT_PRESCRIBER_FILTER_VALUE = "France Travail"
FT_FILTER_VALUE = "France Travail"

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
    "stats_siae_etp": {
        "dashboard_id": 465,
        "tally_popup_form_id": "mYxB7W",
        "tally_embed_form_id": "3qPVOY",
    },
    "stats_siae_orga_etp": {
        "dashboard_id": 440,
        "tally_popup_form_id": "n0POQP",
        "tally_embed_form_id": "wzeYxZ",
    },
    "stats_siae_hiring": {
        "dashboard_id": 185,
        "tally_popup_form_id": "waQPkB",
        "tally_embed_form_id": "nG6J62",
    },
    "stats_siae_auto_prescription": {
        "dashboard_id": 295,
        "tally_popup_form_id": "nW0zPj",
        "tally_embed_form_id": "waGd0v",
    },
    "stats_siae_beneficiaries": {
        "dashboard_id": 550,
        "tally_popup_form_id": "meG0ae",
        "tally_embed_form_id": "wdo89o",
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
        "tally_popup_form_id": "wg4GLl",
        "tally_embed_form_id": "3Xq0Ej",
    },
    "stats_cd_brsa": {
        "dashboard_id": 330,
        "tally_popup_form_id": "wzeYZa",
        "tally_embed_form_id": "w52xL6",
    },
    "stats_cd_orga_etp": {
        "dashboard_id": 485,
        "tally_popup_form_id": "3N0oLB",
        "tally_embed_form_id": "mOoDva",
    },
    "stats_cd_beneficiaries": {
        "dashboard_id": 545,
        "tally_popup_form_id": "wo1GOe",
        "tally_embed_form_id": "w2yPrL",
    },
    #
    # Prescriber stats - FT.
    #
    "stats_ft_conversion_main": {
        "dashboard_id": 169,
        "tally_popup_form_id": "mODeK8",
        "tally_embed_form_id": "3xrPjJ",
    },
    "stats_ft_state_main": {
        "dashboard_id": 496,
        "tally_popup_form_id": "mRG61J",
        "tally_embed_form_id": "3qLKad",
    },
    "stats_ft_beneficiaries": {
        "dashboard_id": 545,
        "tally_popup_form_id": "wo1GOe",
        "tally_embed_form_id": "w2yPrL",
    },
    "stats_ft_hiring": {
        "dashboard_id": 160,
        "tally_popup_form_id": "wo1EYP",
        "tally_embed_form_id": "mBlaYQ",
    },
    #
    # Authorized Prescribers' stats
    #
    "stats_ph_state_main": {
        "dashboard_id": 488,
        "tally_popup_form_id": "3XQ5D4",
        "tally_embed_form_id": "mVNGgv",
    },
    "stats_ph_beneficiaries": {
        "dashboard_id": 545,
        "tally_popup_form_id": "wo1GOe",
        "tally_embed_form_id": "w2yPrL",
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
    "stats_ddets_iae_orga_etp": {
        "dashboard_id": 485,
        "tally_popup_form_id": "3N0oLB",
        "tally_embed_form_id": "mOoDva",
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
    "stats_dreets_iae_orga_etp": {
        "dashboard_id": 485,
        "tally_popup_form_id": "3N0oLB",
        "tally_embed_form_id": "mOoDva",
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
    "stats_dgefp_iae_auto_prescription": {
        "dashboard_id": 515,
        "tally_popup_form_id": "3qLpE2",
        "tally_embed_form_id": "nG6gBj",
    },
    "stats_dgefp_iae_follow_siae_evaluation": {
        "dashboard_id": 516,
        "tally_popup_form_id": "w2XZxV",
        "tally_embed_form_id": "n9Ba6G",
    },
    "stats_dgefp_iae_hiring": {
        "dashboard_id": 520,
        "tally_popup_form_id": "mVLBXv",
        "tally_embed_form_id": "nPpXpQ",
    },
    "stats_dgefp_iae_state": {
        "dashboard_id": 521,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    "stats_dgefp_iae_ph_prescription": {
        "dashboard_id": 522,
        "tally_popup_form_id": "wbWKEo",
        "tally_embed_form_id": "wvPEvQ",
    },
    "stats_dgefp_iae_siae_evaluation": {
        "dashboard_id": 518,
    },
    "stats_dgefp_iae_orga_etp": {
        "dashboard_id": 523,
        "tally_popup_form_id": "3N0oLB",
        "tally_embed_form_id": "mOoDva",
    },
    #
    # Institution stats - DIHAL - nation level.
    #
    "stats_dihal_state": {
        "dashboard_id": 549,
        "tally_popup_form_id": "w2az2j",
        "tally_embed_form_id": "3Nlvzl",
    },
    #
    # Institution stats - IAE Network - nation level.
    #
    "stats_iae_network_hiring": {
        "dashboard_id": 301,
        "tally_popup_form_id": "m6p8aY",
        "tally_embed_form_id": "wvdGol",
    },
    #
    # Institution stats - Convergence France - nation level.
    #
    "stats_convergence_prescription": {
        "dashboard_id": 446,
        "tally_popup_form_id": "31pAq1",
        "tally_embed_form_id": "3ydPWX",
    },
    "stats_convergence_job_application": {
        "dashboard_id": 469,
        "tally_popup_form_id": "3X2xKL",
        "tally_embed_form_id": "mV4LkM",
    },
    "stats_staff_service_indicators": {
        "dashboard_id": 438,
    },
}


SUSPENDED_DASHBOARD_IDS = []


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


def metabase_embedded_url(dashboard_id, *, params=None, with_title=False):
    """
    Creates an embed/signed URL for embedded Metabase dashboards:
    * expiration delay of token
        * long enough so that the filters don't stop working too early and cause user confusion and frustration
        * short enough to mitigate the security risk that the iframe URL could be shared to unauthorized third parties
    * optionally display title of the dashboard in the iframe
    * optional extra parameters typically for locked filters (e.g. allow viewing data of one departement only)
    """
    if params is None:
        params = {}

    payload = {
        "resource": {"dashboard": dashboard_id},
        "params": params,
        "exp": int((timezone.now() + datetime.timedelta(minutes=60)).timestamp()),
    }
    is_titled = "true" if with_title else "false"
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload) + f"#titled={is_titled}"


# Metabase API client
# See: https://www.metabase.com/docs/latest/api/
class Client:
    def __init__(self, base_url):
        self._client = httpx.Client(
            base_url=urljoin(base_url, "/api"),
            headers={
                "X-API-KEY": settings.METABASE_API_KEY,
            },
            timeout=httpx.Timeout(5, read=60),  # Use a not-so-long but not not-so-short read timeout
        )

    @staticmethod
    def _build_metabase_field(field, base_type="type/Text"):
        return ["field", field, {"base-type": base_type}]

    @staticmethod
    def _build_metabase_filter(field, values, base_type="type/Text"):
        return [
            "=",
            Client._build_metabase_field(field, base_type),
            *values,
        ]

    @staticmethod
    def _join_metabase_filters(*filters):
        return [
            "and",
            *filters,
        ]

    def build_query(self, *, select=None, table=None, where=None, group_by=None, limit=None):
        query = {}
        if select:
            query["fields"] = [self._build_metabase_field(field) for field in select]
        if table:
            query["source-table"] = table
        if where:
            query["filter"] = [self._build_metabase_filter(field, values) for field, values in where.items()]
        if group_by:
            query["breakout"] = [self._build_metabase_field(field) for field in group_by]
        if limit:
            query["limit"] = limit

        return query

    def merge_query(self, into, query):
        into = copy.deepcopy(into)

        if "fields" in query:
            into.setdefault("fields", [])
            into["fields"].extend(query["fields"])
        if "filter" in query:
            into.setdefault("filter", [])
            into["filter"] = self._join_metabase_filters(into["filter"], query["filter"])
        if "breakout" in query:
            into.setdefault("breakout", [])
            into["breakout"].extend(query["breakout"])
        if "limit" in query:
            into["limit"] = query["limit"]

        return into

    def build_dataset_query(self, *, database, query):
        return {"database": database, "type": "query", "query": query, "parameters": []}

    def fetch_dataset_results(self, query):
        # /!\ MB is compiled with hardcoded limit:
        #  - `/dataset` limit to 2_000 rows as it is used to preview query results
        #  - `/dataset/{export-format}` limit to 1_000_000 rows as it is used to download queries results
        data = self._client.post("/dataset/json", data={"query": json.dumps(query)}).raise_for_status().json()
        if type(data) is not list:  # `/dataset/json` return a list of rows if successful otherwise it's a dict
            raise Exception(data["error"])
        return data

    def fetch_card_results(self, card, fields=None, filters=None, group_by=None):
        if not any([fields, filters, group_by]):
            return self._client.post(f"/card/{card}/query/json").raise_for_status().json()

        dataset_query = self._client.get(f"/card/{card}").raise_for_status().json()["dataset_query"]
        dataset_query["query"] = self.merge_query(
            dataset_query["query"],
            self.build_query(select=fields, where=filters, group_by=group_by),
        )
        return self.fetch_dataset_results(dataset_query)
