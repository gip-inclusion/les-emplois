import datetime
import logging

import httpx
from django.conf import settings

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.users.enums import Title


logger = logging.getLogger("APIParticulierClient")
SIRET_PLATEFORME_INCLUSION = "13003013300016"
ENDPOINTS = {
    AdministrativeCriteriaKind.AAH: "v3/dss/allocation_adulte_handicape/identite",
    AdministrativeCriteriaKind.PI: "v3/dss/allocation_soutien_familial/identite",
    AdministrativeCriteriaKind.RSA: "v3/dss/revenu_solidarite_active/identite",
}
# From the docs for the 502 HTTP response content:
# “La réponse retournée par le fournisseur de données est invalide et inconnue de notre service.”
UNKNOWN_RESPONSE_FROM_PROVIDER_CNAV_ERROR_CODE = "37999"
UNKNOWN_RESPONSE_FROM_PROVIDER_SECURITE_SOCIALE_ERROR_CODE = "36999"


def client():
    return httpx.Client(
        base_url=settings.API_PARTICULIER_BASE_URL,
        headers={"Authorization": f"Bearer {settings.API_PARTICULIER_TOKEN}"},
    )


def _build_params_from(job_seeker):
    jobseeker_profile = job_seeker.jobseeker_profile
    params = {
        "nomNaissance": job_seeker.last_name.upper(),
        "prenoms[]": job_seeker.first_name.upper().split(" "),
        "anneeDateNaissance": jobseeker_profile.birthdate.year,
        "moisDateNaissance": jobseeker_profile.birthdate.month,
        "jourDateNaissance": jobseeker_profile.birthdate.day,
        "codeCogInseePaysNaissance": f"99{jobseeker_profile.birth_country.code}",
        "sexeEtatCivil": "F" if job_seeker.title == Title.MME else job_seeker.title,
    }
    if jobseeker_profile.is_born_in_france:
        params["codeCogInseeCommuneNaissance"] = jobseeker_profile.birth_place.code
    return params


def _request(client, endpoint, job_seeker):
    params = _build_params_from(job_seeker=job_seeker)
    params["recipient"] = SIRET_PLATEFORME_INCLUSION
    return client.get(endpoint, params=params).raise_for_status().json()


USER_REQUIRED_FIELDS = ["first_name", "last_name", "title"]
JOBSEEKER_PROFILE_REQUIRED_FIELDS = ["birthdate", "birth_country", "birth_place"]


def has_required_info(job_seeker):
    for field in USER_REQUIRED_FIELDS:
        if not getattr(job_seeker, field):
            return False
    profile = job_seeker.jobseeker_profile
    profile_required_fields = JOBSEEKER_PROFILE_REQUIRED_FIELDS.copy()
    if not profile.is_born_in_france:
        profile_required_fields.remove("birth_place")
    for field in profile_required_fields:
        if not getattr(profile, field):
            return False
    return True


def certify_criteria(criteria, client, job_seeker):
    """
    Two criteria are the same between the API and Les emplois: AAH and RSA.
    The "Parent Isolé" criterion is not a subsidy in itself but an administrative terminology.
    See https://www.service-public.fr/particuliers/vosdroits/F15553/
    Regarding the Diagnosis Socio-Professionnel, the beneficiary should already receive
    the Allocation Soutien Familial (ASF) to be considered a Parent Isolé.
    """
    response = _request(client, ENDPOINTS[criteria], job_seeker)
    # Endpoints from the "Prestations sociales" section share the same response schema.
    # See https://particulier.api.gouv.fr/developpeurs/openapi#tag/Prestations-sociales
    data = response["data"]
    certified = data["est_beneficiaire"]
    return {
        "start_at": datetime.date.fromisoformat(data["date_debut_droit"]) if certified else None,
        # When offered by the endpoint, the end_at field is always null. Ignore it.
        "is_certified": certified,
        "raw_response": response,
    }
