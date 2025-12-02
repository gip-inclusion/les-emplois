import logging

import httpx
from data_inclusion.schema import v0
from django.conf import settings


logger = logging.getLogger(__name__)


API_TIMEOUT_SECONDS = 1.0


class DataInclusionApiException(Exception):
    pass


class DataInclusionApiV0Client:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v0/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=API_TIMEOUT_SECONDS,
        )

    def search_services(self, code_insee: str) -> list[dict]:
        params = {
            "code_insee": code_insee,
            "thematiques": [
                v0.Thematique.ACCES_AUX_DROITS_ET_CITOYENNETE.value,
                v0.Thematique.EQUIPEMENT_ET_ALIMENTATION.value,
                v0.Thematique.LOGEMENT_HEBERGEMENT.value,
                v0.Thematique.MOBILITE.value,
                v0.Thematique.REMOBILISATION.value,
            ],
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
