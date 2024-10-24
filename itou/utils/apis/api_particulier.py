import datetime
import logging

import httpx
import tenacity
from django.conf import settings

from itou.asp.models import Country


logger = logging.getLogger("APIParticulierClient")


class ShouldRetryException(httpx.HTTPStatusError):
    """
    This exception can be used to ask Tenacity to retry
    while attaching a response and a request to it.
    """


def client():
    return httpx.Client(
        base_url=settings.API_PARTICULIER_BASE_URL,
        headers={"X-Api-Key": settings.API_PARTICULIER_TOKEN},
    )


def _parse_date(date: str) -> datetime.date | None:
    if date:
        return datetime.date.fromisoformat(date)
    return None


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
    retry=tenacity.retry_if_exception_type(ShouldRetryException),
)
def _request(client, endpoint, job_seeker):
    params = _build_params_from(job_seeker=job_seeker)
    response = client.get(endpoint, params=params)
    error_message = None
    # Bad Request or Unauthorized
    # Same as 503 except we don't retry
    if response.status_code in [400, 401]:
        error_message = "Bad Request" if response.status_code == 400 else "Unauthorized"
        logger.error(error_message, extra={"response": response.json()})
        raise httpx.HTTPStatusError(message=error_message, request=response.request, response=response)
    # Too Many Requests
    elif response.status_code == 429:
        errors = response.json().get("errors")
        if errors:
            error_message = errors[0]
            logger.error(error_message)
        raise ShouldRetryException(message=error_message, request=response.request, response=response)
    # Service unavailable
    elif response.status_code == 503:
        error_message = response.json().get("error")
        if error_message:
            error_message = response.json().get("reason")
        else:
            errors = response.json().get("errors")
            error_message = errors[0].get("title")
        logger.error(error_message)
        raise ShouldRetryException(message=error_message, request=response.request, response=response)
    #  Server error
    elif response.status_code == 504:
        error_message = response.json().get("reason")
        logger.error(error_message)
        raise ShouldRetryException(message=error_message, request=response.request, response=response)
    else:
        response.raise_for_status()
    return response.json()


def revenu_solidarite_active(client, job_seeker):
    data = {
        "start_at": None,
        "end_at": None,
        "is_certified": None,
        "raw_response": None,
    }
    try:
        response_data = _request(client, "/v2/revenu-solidarite-active", job_seeker)
    except httpx.HTTPStatusError as exc:  # not 5XX.
        data["raw_response"] = exc.response.json()
    except tenacity.RetryError as retry_err:  # 429, 503 or 504
        exc = retry_err.last_attempt._exception
        data["raw_response"] = exc.response.json()
    except KeyError as exc:
        logger.info(str(exc))  # FIXME: should be removed
    else:
        data = {
            "start_at": _parse_date(response_data["dateDebut"]),
            "end_at": _parse_date(response_data["dateFin"]),
            "is_certified": response_data["status"] == "beneficiaire",
            "raw_response": response_data,
        }
    return data
