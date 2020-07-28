import logging

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

from itou.external_data.models import ExternalDataImport, ExternalUserData


# PE Connect API data retrieval tools

API_ESD_BASE_URL = settings.API_ESD_BASE_URL

ESD_USERINFO_API = "peconnect-individu/v1/userinfo"
ESD_COORDS_API = "peconnect-coordonnees/v1/coordonnees"
ESD_STATUS_API = "peconnect-statut/v1/statut"
ESD_BIRTHDATE_API = "peconnect-datenaissance/v1/etat-civil"

# FIXME: not registered yet
ESD_COMPENSATION_API = "peconnect-indemnisations/v1/indemnisation"
ESD_PT_TRAININGS_API = "peconnect-formations/v1/formations"
ESD_PT_LICENSES_API = "peconnect-formations/v1/permits"

# Internal ----

logger = logging.getLogger(__name__)


# This part may be refactored with the processing of other APIs
# YAGNI at the moment


def _call_api(api_path, token):
    """ 
    Make a sync call to an API
    For further processing, returning smth else than `None` if considered a success
    """
    url = f"{API_ESD_BASE_URL}/{api_path}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 200:
        return resp.json()
    else:
        # Track it for QoS
        logger.warning(f"API call to: {url} returned status code {resp.status_code}")
        return None


def _fields_or_failed(result, keys):
    if not result:
        return None
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
    # Fields of interest
    keys = ["given_name", "family_name", "gender", "email"]
    return _fields_or_failed(_call_api(ESD_USERINFO_API, token), keys)


def _get_birthdate(token):
    """
    Get birthdate of user (format `YYYY-MM-DDTHH:MM:SSZ`), converted as `datetime` object.

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-datenaissance-v1.html

    """
    key = "dateDeNaissance"
    # code, resp = _call_api(ESD_BIRTHDATE_API, token)
    result = _fields_or_failed(_call_api(ESD_BIRTHDATE_API, token), [key])
    if result:
        return {key: result.get(key)}
    else:
        return None


def _get_status(token):
    """
    Get current status of candidate.

    Returns a dict with codeStatutIndividu field from API:
        * 0: does not seek a job
        * 1: active jobseeker

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-statut-v1.html
    """
    key = "codeStatutIndividu"
    result = _fields_or_failed(_call_api(ESD_STATUS_API, token), [key])
    if result:
        code = result.get(key)
        return {key: int(code)}
    else:
        return None


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
    return _fields_or_failed(_call_api(ESD_COORDS_API, token), keys)


def _get_compensations(token):
    """
    Get user "compensations" (social allowance):

    Return a dict with fields:
        * beneficiairePrestationSolidarite (has one or more of AER, AAH, ASS, RSA)
        * beneficiaireAssuranceChomage (has ARE or ASP)

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-indemnisations-v1.html
    """
    keys = ["beneficiairePrestationSolidarite", "beneficiaireAssuranceChomage"]
    return _fields_or_failed(_call_api(ESD_COMPENSATION_API, token), keys)


def _get_aggregated_user_data(token):
    """
    Aggregates all needed user data before formatting and storage.
    Returns a pair status and a "flat" dict.
    """
    # Include API results "à volonté"
    results = [
        _get_userinfo(token),
        _get_birthdate(token),
        _get_status(token),
        _get_address(token),
        _get_compensations(token),
    ]

    ok = all(results)
    partial = not ok and any(results)
    cleaned_results = [part for part in results if part]
    resp = dict()

    if ok:
        status = ExternalDataImport.STATUS_OK
    elif partial:
        status = ExternalDataImport.STATUS_PARTIAL
    else:
        status = ExternalDataImport.STATUS_FAILED

    for result in cleaned_results:
        resp = {**resp, **result}

    return status, resp


# External user data from PE Connect API:
# * transform raw data from API
# * dispatch data into models if possible
# * or store as key / value if needed


def _store_user_data(user, status, data):
    # Set a trace of data import, whatever the resulting status
    data_import = ExternalDataImport.objects.last_pe_import_for_user(user)

    # If user data already exists, erase and replace
    if data_import:
        data_import.delete()

    data_import = ExternalDataImport(user=user, status=status, source=ExternalDataImport.DATA_SOURCE_PE_CONNECT)
    data_import.save()

    if status == ExternalDataImport.STATUS_FAILED:
        return data_import

    # FIXME: remove
    print(f"Data: {data}")

    # User part:
    # Can be directly "inserted" in to the model
    if data.get("dateDeNaissance"):
        user.birthdate = user.birthdate or parse_datetime(data.get("dateDeNaissance"))

    user.address_line_1 = "" or user.address_line_1 or data.get("adresse4")
    user.post_code = user.post_code or data.get("codePostal")
    user.city = user.city or data.get("libelleCommune")

    user.save()

    # The following will be stored as k/v
    external_user_data = []
    result_keys = list(data.keys())

    if "codeStatutIndividu" in result_keys:
        external_user_data.append(
            ExternalUserData(key=ExternalUserData.KEY_IS_PE_JOBSEEKER, value=data.get("codeStatutIndividu"))
        )

    if "beneficiairePrestationSolidarite" in result_keys:
        external_user_data.append(
            ExternalUserData(
                key=ExternalUserData.KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE,
                value=data.get("beneficiairePrestationSolidarite"),
            )
        )

    # ...

    for elt in external_user_data:
        elt.data_import = data_import

    ExternalUserData.objects.bulk_create(external_user_data)

    return data_import


#  Public ----


def import_user_data(user, token):
    """
    Import external user data via PE Connect
    Returns a valid ExternalDataImport object when result is partial or ok.
    """
    # Create a new import with a pending status (wil be async)
    data_import = ExternalDataImport(
        user=user, status=ExternalDataImport.STATUS_PENDING, source=ExternalDataImport.DATA_SOURCE_PE_CONNECT
    )
    data_import.save()

    status, result = _get_aggregated_user_data(token)
    data_import = _store_user_data(user, status, result)

    # At the moment, results are stored only if OK
    if status == ExternalDataImport.STATUS_OK:
        logger.info(f"Stored external data for user {user}")
    elif status == ExternalDataImport.STATUS_PARTIAL:
        logger.warning(f"Could only fetch partial results for {user}")
    else:
        logger.error(f"Could not fetch any data for {user}: not data stored")

    return data_import
