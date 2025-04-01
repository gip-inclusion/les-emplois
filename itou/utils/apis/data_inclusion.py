import logging

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)


API_TIMEOUT_SECONDS = 1.0
API_THEMATIQUES = [
    "acces-aux-droits-et-citoyennete",
    "equipement-et-alimentation",
    "logement-hebergementmobilite",
    "numerique",
    "remobilisation",
]


class DataInclusionApiException(Exception):
    pass


class DataInclusionApiClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=API_TIMEOUT_SECONDS,
        )

    def search_services(self, code_insee: str) -> list[dict]:
        params = {
            "code_insee": code_insee,
            "thematiques": API_THEMATIQUES,
            "score_qualite_minimum": settings.API_DATA_INCLUSION_SCORE_QUALITE_MINIMUM,
        }
        if settings.API_DATA_INCLUSION_SOURCES:
            params["sources"] = settings.API_DATA_INCLUSION_SOURCES.split(",")
        try:
            response = self.client.get(
                "/search/services",
                params=params,
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("data.inclusion request error code_insee=%s error=%s", code_insee, exc)
            raise DataInclusionApiException()

        try:
            return [r["service"] for r in response.json()["items"]]
        except KeyError as exc:
            logger.info("data.inclusion result error code_insee=%s error=%s", code_insee, exc)
            raise DataInclusionApiException()

    def retrieve_service(self, source: str, id_: str) -> dict:
        try:
            return (
                self.client.get(
                    f"/services/{source}/{id_}",
                )
                .raise_for_status()
                .json()
            )
        except httpx.HTTPError as exc:
            logger.info("data.inclusion request error source=%s service_id=%s error=%s", source, id_, exc)
            raise DataInclusionApiException()
