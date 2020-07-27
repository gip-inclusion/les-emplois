import logging

import requests
from django.conf import settings


# PE Connect API data retrieval tools

API_ESD_BASE_URL = settings.API_ESD_BASE_URL

ESD_USERINFO_API = "peconnect-individu/v1/userinfo"
ESD_COORDS_API = "peconnect-coordonnees/v1/coordonnees"
ESD_STATUS_API = "peconnect-statut/v1/statut"
ESD_BIRTHDATE_API = "peconnect-datenaissance/v1/etat-civil"

# FIXME: check if needed and with complete data
ESD_COMPENSATION_API = "peconnect-indemnisations/v1/indemnisation"
ESD_PT_TRAININGS_API = "peconnect-formations/v1/formations"
ESD_PT_LICENSES_API = "peconnect-formations/v1/permits"

N_A = None

# Internal ----

logger = logging.getLogger(__name__)


def _call_api(api_path, token):
    url = f"{API_ESD_BASE_URL}/{api_path}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 200:
        return resp.json()
    else:
        # Track it for QoS
        logger.warning(f"API call to: {url} returned status code {resp.status_code}")
        return None


def _fields_or_nas(result, keys):
    if not result:
        return {k: N_A for k in keys}
    else:
        return {k: v for k, v in result.items() if k in keys}


def _get_userinfo(token):
    """
    Get main info from user:
        * first and family names
        * gender
        * email address

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-individu-v1.html

    """
    keys = ["given_name", "family_name", "gender", "email"]
    return _fields_or_nas(_call_api(ESD_USERINFO_API, token), keys)


def _get_birthdate(token):
    """
    Get birthdate of user (format `YYYY-MM-DDTHH:MM:SSZ`), converted as `datetime` object.

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-datenaissance-v1.html 

    """
    key = "dateDeNaissance"
    # code, resp = _call_api(ESD_BIRTHDATE_API, token)
    result = _fields_or_nas(_call_api(ESD_BIRTHDATE_API, token), [key])
    return {key: result.get(key) or N_A}


def _get_status(token):
    """
    Get current status of candidate.

    Returns a dict with codeStatutIndividu field from API:
        * 0: does not seek a job
        * 1: active jobseeker

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-statut-v1.html
    """
    key = "codeStatutIndividu"
    result = _fields_or_nas(_call_api(ESD_STATUS_API, token), [key])
    code = result.get(key)
    return {key: int(code) if code else N_A}


def _get_address(token):
    """
    Get current address of the candidate:

    Returns a dict with fields:
        * adresse1
        * adresse2
        * adresse3
        * adresse4
        * codePostal
        * codeINSEE
        * libelleCommune

    Does not return country related fields (only France ATM)

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-coordonnees-v1.html
    """
    keys = ["adresse1", "adresse2", "adresse3", "adresse4", "codePostal", "codeINSEE", "libelleCommune"]
    return _fields_or_nas(_call_api(ESD_COORDS_API, token), keys)


#  Public ----


def get_aggregated_user_data(token):
    """
    Aggregates all needed user data before formatting and storage,
    and return as a dict.
    KISS: simple and flat
    """
    # TBD: include API results "à volonté"
    return {**_get_userinfo(token), **_get_birthdate(token), **_get_status(token), **_get_address(token)}
