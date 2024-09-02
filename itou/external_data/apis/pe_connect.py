import logging

import httpx
from django.conf import settings
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils.dateparse import parse_datetime

from itou.external_data.models import ExternalDataImport, JobSeekerExternalData
from itou.users import enums as users_enums


# PE Connect API data retrieval tools
ESD_USERINFO_API = "peconnect-individu/v1/userinfo"
ESD_COORDS_API = "peconnect-coordonnees/v1/coordonnees"
ESD_STATUS_API = "peconnect-statut/v1/statut"
ESD_BIRTHDATE_API = "peconnect-datenaissance/v1/etat-civil"

# FIXME: not registered yet
ESD_COMPENSATION_API = "peconnect-indemnisations/v1/indemnisation"
ESD_PT_TRAININGS_API = "peconnect-formations/v1/formations"
ESD_PT_LICENSES_API = "peconnect-formations/v1/permits"

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


def _get_userinfo(token):
    """
    Get main info from user:
        * first and family names
        * gender
        * email address

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-individu-v1.html
    """  # noqa: E501
    # Fields of interest
    keys = ["given_name", "family_name", "gender", "email"]
    return _fields_or_failed(_call_api(ESD_USERINFO_API, token), keys)


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


def _get_status(token):
    """
    Get current status of candidate.

    Returns a dict with codeStatutIndividu field from API:
        * 0: does not seek a job
        * 1: active jobseeker

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-statut-v1.html
    """  # noqa: E501
    key = "codeStatutIndividu"
    result = _fields_or_failed(_call_api(ESD_STATUS_API, token), [key])
    if result:
        code = result.get(key)
        return {key: int(code)}

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


def _get_compensations(token):
    """
    Get user "compensations" (social allowance):

    Return a dict with fields:
        * beneficiairePrestationSolidarite (has one or more of AER, AAH, ASS, RSA)
        * beneficiaireAssuranceChomage (has ARE or ASP)

    See: https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-indemnisations-v1.html
    """  # noqa: E501
    keys = ["beneficiairePrestationSolidarite", "beneficiaireAssuranceChomage"]
    return _fields_or_failed(_call_api(ESD_COMPENSATION_API, token), keys)


def get_aggregated_user_data(token):
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

    if ok:
        status = ExternalDataImport.STATUS_OK
    elif partial:
        status = ExternalDataImport.STATUS_PARTIAL
    else:
        status = ExternalDataImport.STATUS_FAILED

    user_data = {}
    for result in cleaned_results:
        user_data.update(result)

    return status, user_data


def _model_fields_changed(initial, final_instance):
    """
    Return an array with fields of the model_instance object that will be changed on `save()`
    """
    final = model_to_dict(final_instance)
    class_name = type(final_instance).__name__
    return [f"{class_name}/{final_instance.pk}/{k}" for k, v in initial.items() if v != final.get(k)]


# External user data from PE Connect API:
# * transform raw data from API
# * dispatch data into models if possible
# * or store as key / value if needed


def set_pe_data_import_from_user_data(pe_data_import, user, status, user_data):
    """
    Store user data and produce a "report" containing a JSON object, with these fields:
        - fields_fetched (array): successfully imported field names
        - fields_failed (array): fields that could not be fetched (API error...)
        - fields_updated (array): updated fields in the db each of form:
            `class_name/pk/field_name` (f.i. `User/10/birthdate`)

    Return a ExternalDataImport object containing outcome of the data import
    """
    fields_fetched = [k for k, v in user_data.items() if v is not None]
    fields_failed = [k for k, v in user_data.items() if v is None]

    job_seeker_data, _ = JobSeekerExternalData.objects.get_or_create(user=user, data_import=pe_data_import)

    # Record changes on model objects:
    initial_job_seekeer_data = model_to_dict(job_seeker_data)
    initial_job_seeker_profile = model_to_dict(user.jobseeker_profile)
    initial_user = model_to_dict(user)

    for k in fields_fetched:
        pe_connect_provider = users_enums.IdentityProvider.PE_CONNECT
        v = user_data.get(k)

        # User part:
        if k == "dateDeNaissance":
            new_value = user.jobseeker_profile.birthdate or parse_datetime(v)
            user.jobseeker_profile.birthdate = new_value
            user.update_external_data_source_history_field(pe_connect_provider, "birthdate", new_value)
        elif k == "adresse4":
            new_value = "" or user.address_line_1 or v
            user.address_line_1 = new_value
            user.update_external_data_source_history_field(pe_connect_provider, "address_line_1", new_value)
        elif k == "adresse2":
            new_value = "" or user.address_line_2 or v
            user.address_line_2 = new_value
            user.update_external_data_source_history_field(pe_connect_provider, "address_line_2", new_value)
        elif k == "codePostal":
            new_value = user.post_code or v
            user.post_code = new_value
            user.update_external_data_source_history_field(pe_connect_provider, "post_code", new_value)
        elif k == "libelleCommune":
            new_value = user.city or v
            user.city = new_value
            user.update_external_data_source_history_field(pe_connect_provider, "city", new_value)

        # JobSeekerExternalData part:
        if k == "codeStatutIndividu":
            new_value = v == 1
            job_seeker_data.is_pe_jobseeker = new_value
            user.update_external_data_source_history_field(pe_connect_provider, "is_pe_jobseeker", new_value)
        elif k == "beneficiairePrestationSolidarite":
            job_seeker_data.has_minimal_social_allowance = v
            user.update_external_data_source_history_field(pe_connect_provider, "has_minimal_social_allowance", v)

    # Check updated fields
    # To be done before saving objects:
    fields_updated = (
        _model_fields_changed(initial_user, user)
        + _model_fields_changed(initial_job_seekeer_data, job_seeker_data)
        + _model_fields_changed(initial_job_seeker_profile, user.jobseeker_profile)
    )

    # Atomicity in outer call
    user.save()
    user.jobseeker_profile.save(update_fields={"birthdate"})
    job_seeker_data.save()

    report = {"fields_fetched": fields_fetched, "fields_failed": fields_failed, "fields_updated": fields_updated}
    pe_data_import.status = status
    pe_data_import.report = report
    return pe_data_import


#  Public


def import_user_pe_data(
    user,
    token,
    pe_data_import=None,
):
    """
    Import external user data via PE Connect
    Returns a valid ExternalDataImport object when result is PARTIAL or OK.
    """
    if not pe_data_import:
        pe_data_import = ExternalDataImport.objects.create(
            source=ExternalDataImport.DATA_SOURCE_PE_CONNECT, user=user, status=ExternalDataImport.STATUS_PENDING
        )

        try:
            # External requests
            status, user_data = get_aggregated_user_data(token)
            with transaction.atomic():
                # A refactoring would be helpful to split user/job seeker saving
                # and to use the status before calling save()
                # Save user and job seeker data
                set_pe_data_import_from_user_data(pe_data_import, user, status, user_data)
                pe_data_import.save()

            if status == ExternalDataImport.STATUS_OK:
                logger.info("Stored external data for user %s", user)
            elif status == ExternalDataImport.STATUS_PARTIAL:
                logger.warning("Could only fetch partial results for %s", user)
            else:
                logger.warning("Could not fetch any data for %s: not data stored", user)
        except Exception as e:
            logger.warning("Data import for %s failed: %s", user, e)
            pe_data_import.status = ExternalDataImport.STATUS_FAILED
            pe_data_import.save()

    return pe_data_import
