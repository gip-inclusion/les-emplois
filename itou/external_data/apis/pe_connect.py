import contextlib
import logging

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from itou.external_data.enums import RetrievalStatus
from itou.utils import triggers


# PE Connect API data retrieval tools
ESD_COORDS_API = "peconnect-coordonnees/v1/coordonnees"
ESD_BIRTHDATE_API = "peconnect-datenaissance/v1/etat-civil"


# Internal
logger = logging.getLogger(__name__)


# This part may be refactored with the processing of other APIs
# YAGNI at the moment


def _call_api(api_path, token):
    """
    Make a sync call to an API
    For further processing, returning something else than `None` is considered a success
    """
    url = f"{settings.API_ESD['BASE_URL']}/{api_path}"
    response = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=settings.REQUESTS_TIMEOUT)
    if response.status_code == 200:
        result = response.json()
        # logger.debug(f"CALL {url}: {result}")
        return result

    # Track it for QoS
    logger.warning("API call to: %s returned status code %s", url, response.status_code)
    return None


def _fields_or_failed(result, keys):
    if not result:
        return None

    return {k: v for k, v in result.items() if k in keys}


def _get_birthdate(token):
    """
    Get birthdate of user (format `YYYY-MM-DDTHH:MM:SSZ`), converted as `datetime` object.

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-datenaissance-v1.html
    """  # noqa: E501
    key = "dateDeNaissance"
    # code, resp = _call_api(ESD_BIRTHDATE_API, token)
    result = _fields_or_failed(_call_api(ESD_BIRTHDATE_API, token), [key])
    if result:
        return {key: result.get(key)}

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
    """  # noqa: E501
    keys = ["adresse1", "adresse2", "adresse3", "adresse4", "codePostal", "codeINSEE", "libelleCommune"]
    return _fields_or_failed(_call_api(ESD_COORDS_API, token), keys)


def get_aggregated_user_data(token):
    """
    Aggregates all needed user data before formatting and storage.
    Returns a pair status and a "flat" dict.
    """
    # Include API results "à volonté"
    results = [
        _get_birthdate(token),
        _get_address(token),
    ]

    ok = all(results)
    partial = not ok and any(results)
    cleaned_results = [part for part in results if part]

    if ok:
        status = RetrievalStatus.OK
    elif partial:
        status = RetrievalStatus.PARTIAL
    else:
        status = RetrievalStatus.FAILED

    user_data = {}
    for result in cleaned_results:
        user_data.update(result)

    return status, user_data


# External user data from PE Connect API:
# * transform raw data from API
# * dispatch data into models if possible
# * or store as key / value if needed


def set_pe_data_import_from_user_data(user, user_data):
    fields_fetched = [k for k, v in user_data.items() if v is not None]

    user_has_address = user.address_on_one_line
    for k in fields_fetched:
        v = user_data.get(k)

        # User part:
        if k == "dateDeNaissance":
            new_value = user.jobseeker_profile.birthdate or timezone.localdate(parse_datetime(v))
            user.jobseeker_profile.birthdate = new_value
        elif k == "adresse4" and not user_has_address:
            user.address_line_1 = v
        elif k == "adresse2" and not user_has_address:
            user.address_line_2 = v
        elif k == "codePostal" and not user_has_address:
            user.post_code = v
        elif k == "libelleCommune" and not user_has_address:
            user.city = v

    # Atomicity in outer call
    user.save()
    user.jobseeker_profile.save(update_fields={"birthdate"})


#  Public


def import_user_pe_data(
    user,
    token,
    triggers_context=None,
):
    """
    Import external user data via PE Connect
    Returns a valid ExternalDataImport object when result is PARTIAL or OK.
    """

    try:
        # External requests
        status, user_data = get_aggregated_user_data(token)
        with (
            transaction.atomic(),
            triggers.context(**triggers_context) if triggers_context is not None else contextlib.nullcontext(),
        ):
            set_pe_data_import_from_user_data(user, user_data)

        if status == RetrievalStatus.OK:
            logger.info("Stored external data for user=%s", user.pk)
        elif status == RetrievalStatus.PARTIAL:
            logger.warning("Could only fetch partial results for user=%s", user.pk)
        else:
            logger.warning("Could not fetch any data for user=%s: not data stored", user.pk)
    except Exception as e:
        logger.warning("Data import for user=%s failed: %s", user.pk, e)
