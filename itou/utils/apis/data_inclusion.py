import logging
from urllib.parse import urljoin

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)


API_TIMEOUT_SECONDS = 1.0
API_THEMATIQUES = [
    "acces-aux-droits-et-citoyennete",
    "accompagnement-social-et-professionnel-personnalise",
    "apprendre-francais",
    "choisir-un-metier",
    "mobilite",
    "trouver-un-emploi",
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
        try:
            response = self.client.get(
                "/search/services",
                params={
                    "code_insee": code_insee,
                    "sources": settings.API_DATA_INCLUSION_SOURCES,
                    "thematiques": API_THEMATIQUES,
                },
            )
            response.raise_for_status()
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
            response = self.client.get(
                f"/services/{source}/{id_}",
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("data.inclusion request error source=%s service_id=%s error=%s", source, id_, exc)
            raise DataInclusionApiException()

        return response.json()


def make_service_redirect_url(source: str, service_id: str) -> str:
    return urljoin(settings.API_DATA_INCLUSION_BASE_URL, f"services/{source}/{service_id}/redirige?depuis=les-emplois")
