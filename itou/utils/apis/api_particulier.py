import logging

import httpx
import tenacity
from django.conf import settings


class APIParticulierClient:
    def __init__(self):
        self.client = httpx.Client(
            headers={"X-Api-Key": settings.API_PARTICULIER_TOKEN}, base_url=settings.API_PARTICULIER_BASE_URL
        )
        self.logger = logging.getLogger("APIParticulierClient")

    # @property
    # def default_params(self, data):
    #     return {
    #             "nomNaissance": data.get("last_name"),
    #             "prenoms[]": data.get("first_name").split(" "),
    #             "anneeDateDeNaissance": data.get("birth_year"),
    #             "moisDateDeNaissance": data.get("birth_month"),
    #             "jourDateDeNaissance": data.get("birth_day"),
    #             "codeInseeLieuDeNaissance": data.get("birth_place_code"),
    #             "codePaysLieuDeNaissance": data.get("birth_country_code"),
    #             "sexe": data.get("gender"),
    #         }

    @tenacity.retry(
        wait=tenacity.wait_fixed(2),
        stop=tenacity.stop_after_attempt(4),
        retry=tenacity.retry_if_exception_type(httpx.RequestError),
    )
    def _request(self, endpoint, params=None):
        response = self.client.get(endpoint, params=params)
        if response.status_code in [503, 504]:
            reason = response.json().get("reason")
            message = f"{response.url=} reason:{reason}"
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
