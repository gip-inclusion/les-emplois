import contextlib
import logging

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

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
        fetched_birthdate = None
        if not user.jobseeker_profile.birthdate:
            birthdate_info = _get_birthdate(token)
            if birthdate_info is None:
                logger.warning("Could not fetch birthdate for user=%s", user.pk)
            else:
                fetched_birthdate = timezone.localdate(parse_datetime(birthdate_info["dateDeNaissance"]))

        fetched_address = None
        if not user.address_on_one_line:
            address_info = _get_address(token)
            if address_info is None:
                logger.warning("Could not fetch address for user=%s", user.pk)
            elif all(address_info.get(k) for k in ["adresse4", "codePostal", "libelleCommune"]):
                fetched_address = address_info
            else:
                logger.warning("Fetched address for user=%d seems incomplete", user.pk)

        if not fetched_birthdate and not fetched_address:
            logger.info("Nothing to do for user=%d", user.pk)
            return

        with (
            transaction.atomic(),
            triggers.context(**triggers_context) if triggers_context is not None else contextlib.nullcontext(),
        ):
            if fetched_birthdate:
                user.jobseeker_profile.birthdate = fetched_birthdate
                user.jobseeker_profile.save(update_fields={"birthdate"})
                logger.info("Updated birthdate for user=%d", user.pk)

            if fetched_address:
                user.address_line_1 = fetched_address["adresse4"]
                user.address_line_2 = fetched_address.get("adresse2", "")
                user.post_code = fetched_address["codePostal"]
                user.city = fetched_address["libelleCommune"]
                user.save(update_fields={"address_line_1", "address_line_2", "post_code", "city"})
                logger.info("Updated address for user=%d", user.pk)

    except Exception as e:
        logger.warning("Data import for user=%s failed: %s", user.pk, e)
