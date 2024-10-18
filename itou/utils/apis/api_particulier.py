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

    pass


class APIParticulierClient:
    def __init__(self, job_seeker=None):
        self.client = httpx.Client(
            headers={"X-Api-Key": settings.API_PARTICULIER_TOKEN}, base_url=settings.API_PARTICULIER_BASE_URL
        )
        self.job_seeker = job_seeker

    @staticmethod
    def format_date(date: str) -> datetime.datetime:
        return datetime.datetime.strptime(date, "%Y-%m-%d") if date else ""

    @classmethod
    def _build_params_from(cls, job_seeker):
        jobseeker_profile = job_seeker.jobseeker_profile
        requested_objects = [
            jobseeker_profile.birth_country,
            jobseeker_profile.birthdate,
            job_seeker.first_name,
            job_seeker.last_name,
            job_seeker.title,
        ]
        # TODO(cms): add JobSeekerProfile.is_born_in_france
        born_in_france = (
            jobseeker_profile.birth_country and jobseeker_profile.birth_country.group == Country.Group.FRANCE
        )
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
    def _request(self, endpoint, params=None):
        params = self._build_params_from(job_seeker=self.job_seeker)
        response = self.client.get(endpoint, params=params)
        error_message = None
        # Too Many Requests
        if response.status_code == 429:
            errors = response.json().get("errors")
            if errors:
                error_message = errors[0]
            raise ShouldRetryException(message=error_message, request=response.request, response=response)
        # Bad params.
        # Same as 503 except we don't retry.
        elif response.status_code in (400, 401):
            errors = response.json()["errors"]
            raise httpx.HTTPStatusError(message=error_message, request=response.request, response=response)
        # Service unavailable
        elif response.status_code == 503:
            error_message = response.json().get("error")
            if error_message:
                error_message = response.json().get("reason")
            else:
                errors = response.json().get("errors")
                error_message = errors[0].get("title")
            raise ShouldRetryException(message=error_message, request=response.request, response=response)
        #  Server error
        elif response.status_code == 504:
            error_message = response.json().get("reason")
            raise ShouldRetryException(message=error_message, request=response.request, response=response)
        else:
            response.raise_for_status()
        return response.json()

    def revenu_solidarite_active(self):
        data = {"start_at": "", "end_at": "", "is_certified": "", "raw_response": ""}
        error_message = None
        try:
            data = self._request("/v2/revenu-solidarite-active")
        except httpx.HTTPStatusError as exc:  # not 5XX.
            error_message = f"{exc.response.status_code}: {exc.response.json()} {exc.response.url=}"
        except tenacity.RetryError as retry_err:  # 429, 503 or 504
            exc = retry_err.last_attempt._exception
            error_message = f"{exc.response.status_code}: {exc.response.json()} {exc.response.url=}"
        except KeyError as exc:
            error_message = f"KeyError: {exc=}"
        else:
            data = {
                "start_at": self.format_date(data["dateDebut"]),
                "end_at": self.format_date(data["dateFin"]),
                "is_certified": data["status"] == "beneficiaire",
                "raw_response": data,
            }
        finally:
            if error_message:
                data["raw_response"] = error_message
                logger.warning(error_message)
            return data
