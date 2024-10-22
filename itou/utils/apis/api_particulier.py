import datetime
import logging

import httpx
import tenacity
from django.conf import settings

from itou.asp.models import Country


logger = logging.getLogger("APIParticulierClient")


def client():
    return httpx.Client(
        base_url=settings.API_PARTICULIER_BASE_URL,
        headers={"X-Api-Key": settings.API_PARTICULIER_TOKEN},
    )


def _format_date(date: str) -> datetime.datetime:
    return datetime.datetime.strptime(date, "%Y-%m-%d") if date else ""


def _build_params_from(job_seeker):
    jobseeker_profile = job_seeker.jobseeker_profile
    requested_objects = [
        jobseeker_profile.birth_country,
        jobseeker_profile.birthdate,
        job_seeker.first_name,
        job_seeker.last_name,
        job_seeker.title,
    ]
    # TODO(cms): add JobSeekerProfile.is_born_in_france
    born_in_france = jobseeker_profile.birth_country and jobseeker_profile.birth_country.group == Country.Group.FRANCE
    if born_in_france:
        requested_objects.append(jobseeker_profile.birth_place)
    if not all(requested_objects):
        raise KeyError(f"Missing parameters for {job_seeker.public_id=}. Unable to call the API Particulier.")

    params = {
        "nomNaissance": job_seeker.last_name.upper(),
        "prenoms[]": job_seeker.first_name.upper().split(" "),
        "anneeDateDeNaissance": jobseeker_profile.birthdate.year,
        "moisDateDeNaissance": jobseeker_profile.birthdate.month,
        "jourDateDeNaissance": jobseeker_profile.birthdate.day,
        "codePaysLieuDeNaissance": f"99{jobseeker_profile.birth_country.code}",
        "sexe": "F" if job_seeker.title == "MME" else job_seeker.title,
    }
    if born_in_france:
        params["codeInseeLieuDeNaissance"] = jobseeker_profile.birth_place.code
    return params


@tenacity.retry(
    wait=tenacity.wait_fixed(2),
    stop=tenacity.stop_after_attempt(4),
    retry=tenacity.retry_if_exception_type(httpx.RequestError),
)
def _request(client, endpoint, job_seeker):
    params = _build_params_from(job_seeker=job_seeker)
    response = client.get(endpoint, params=params)
    if response.status_code == 504:
        reason = response.json().get("reason")
        logger.error(f"{response.url=} {reason=}")
        raise httpx.RequestError(message=reason)
    elif response.status_code == 503:
        errors = response.json()["errors"]
        reason = errors[0].get("title")
        for error in errors:
            logger.error(f"{response.url=} {error['title']}")
        raise httpx.RequestError(message=reason)
    else:
        response.raise_for_status()
    return response.json()


def revenu_solidarite_active(client, job_seeker):
    data = {
        "start_at": "",
        "end_at": "",
        "is_certified": "",
        "raw_response": "",
    }
    try:
        data = _request(client, "/v2/revenu-solidarite-active", job_seeker)
    except httpx.HTTPStatusError as exc:  # not 5XX.
        logger.info(f"Beneficiary not found. {job_seeker.public_id=}")
        data["raw_response"] = exc.response.json()
    except tenacity.RetryError as retry_err:  # 503 or 504
        exc = retry_err.last_attempt._exception
        data["raw_response"] = str(exc)
    except KeyError as exc:
        data["raw_response"] = str(exc)
    else:
        data = {
            "start_at": _format_date(data["dateDebut"]),
            "end_at": _format_date(data["dateFin"]),
            "is_certified": data["status"] == "beneficiaire",
            "raw_response": data,
        }
    return data
