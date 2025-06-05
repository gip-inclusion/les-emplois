import datetime
import logging

import httpx
from django.conf import settings

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.utils.logging import suppress_logs


logger = logging.getLogger("APIParticulierClient")


def client():
    return httpx.Client(
        base_url=settings.API_PARTICULIER_BASE_URL,
        headers={"X-Api-Key": settings.API_PARTICULIER_TOKEN},
    )


def _build_params_from(job_seeker):
    jobseeker_profile = job_seeker.jobseeker_profile
    params = {
        "nomNaissance": job_seeker.last_name.upper(),
        "prenoms[]": job_seeker.first_name.upper().split(" "),
        "anneeDateDeNaissance": jobseeker_profile.birthdate.year,
        "moisDateDeNaissance": jobseeker_profile.birthdate.month,
        "jourDateDeNaissance": jobseeker_profile.birthdate.day,
        "codePaysLieuDeNaissance": f"99{jobseeker_profile.birth_country.code}",
        "sexe": "F" if job_seeker.title == "MME" else job_seeker.title,
    }
    if jobseeker_profile.is_born_in_france:
        params["codeInseeLieuDeNaissance"] = jobseeker_profile.birth_place.code
    return params


def _request(client, endpoint, job_seeker):
    params = _build_params_from(job_seeker=job_seeker)
    # HTTPX logs query params but, in this case, it contains personal data
    # that cannot end up in Datadog.
    with suppress_logs(logger=logging.getLogger("httpx")):
        response = client.get(endpoint, params=params).raise_for_status().json()
    return response


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
    endpoint_mapping = {
        AdministrativeCriteriaKind.AAH: "/v2/allocation-adulte-handicape",
        AdministrativeCriteriaKind.PI: "/v2/allocation-soutien-familial",
        AdministrativeCriteriaKind.RSA: "/v2/revenu-solidarite-active",
    }
    response = _request(client, endpoint_mapping[criteria], job_seeker)
    # Endpoints from the "Prestations sociales" section share the same response schema.
    # See https://particulier.api.gouv.fr/developpeurs/openapi#tag/Prestations-sociales
    certified = response["status"] == "beneficiaire"
    return {
        "start_at": datetime.date.fromisoformat(response["dateDebut"]) if certified else None,
        # When offered by the endpoint, the end_at field is always null. Ignore it.
        "is_certified": certified,
        "raw_response": response,
    }
