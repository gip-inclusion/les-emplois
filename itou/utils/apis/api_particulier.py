import datetime
import logging

import httpx
import tenacity
from django.conf import settings


class APIParticulierClient:
    def __init__(self, job_seeker=None):
        self.client = httpx.Client(
            headers={"X-Api-Key": settings.API_PARTICULIER_TOKEN}, base_url=settings.API_PARTICULIER_BASE_URL
        )
        self.job_seeker = job_seeker
        self.logger = logging.getLogger("APIParticulierClient")

    @classmethod
    def _build_params_from(cls, job_seeker):
        # TODO: transform into a Dataclass
        """
        users = (
            User.objects.filter(pk__in=users_pk)
            .values(
                "first_name",
                "last_name",
                "birthdate",
                "title",
            )
            .annotate(birth_country_code=F("jobseeker_profile__birth_country__code"))
            .annotate(birth_place_code=F("jobseeker_profile__birth_place__code"))
        )
        """
        gender = None
        match job_seeker["title"]:
            case "MME":
                gender = "F"
            case "M":
                gender = "M"
            case _:
                pass
        return {
            "nomNaissance": job_seeker["last_name"],
            "prenoms[]": job_seeker["first_name"].split(" "),
            "anneeDateDeNaissance": job_seeker["birthdate"].year,
            "moisDateDeNaissance": job_seeker["birthdate"].month,
            "jourDateDeNaissance": job_seeker["birthdate"].day,
            "codeInseeLieuDeNaissance": job_seeker["birth_place_code"],
            "codePaysLieuDeNaissance": f"99{job_seeker['birth_country_code']}",
            "sexe": gender,
        }

    @tenacity.retry(
        wait=tenacity.wait_fixed(2),
        stop=tenacity.stop_after_attempt(4),
        retry=tenacity.retry_if_exception_type(httpx.RequestError),
    )
    def _request(self, endpoint, params=None):
        response = self.client.get(endpoint, params=params)
        if response.status_code in [503, 504]:
            reason = response.json().get("reason")
            message = f"{response.url=} {reason=}"
            self.logger.error(message)
            raise httpx.RequestError(message=message)
        else:
            response.raise_for_status()
        return response

    def test_scope_validity(self):
        response = self._request("/introspect").json()
        return all(
            scope in response["scopes"]
            for scope in [
                "revenu_solidarite_active",
                "revenu_solidarite_active_majoration",
                "allocation_adulte_handicape",
                "allocation_soutien_familial",
            ]
        )

    def revenu_solidarite_active(self):
        params = self._build_params_from(job_seeker=self.job_seeker)
        response = self._request("/v2/revenu-solidarite-active", params=params)
        data = response.json()
        is_certified = data["status"] == "beneficiaire"
        try:
            start = datetime.datetime.strptime(data["dateDebut"], "%Y-%m-%d")
            end = datetime.datetime.strptime(data["dateFin"], "%Y-%m-%d")
            certification_period = (start, end)
        except ValueError:
            certification_period = ""
        return data, is_certified, certification_period
