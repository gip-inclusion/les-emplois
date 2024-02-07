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
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def services(self, code_insee):
        try:
            response = httpx.request(
                "GET",
                urljoin(self.base_url, "search/services"),
                params={
                    "code_insee": code_insee,
                    "sources": settings.API_DATA_INCLUSION_SOURCES,
                    "thematiques": API_THEMATIQUES,
                },
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                timeout=API_TIMEOUT_SECONDS,
            )
            return [r["service"] for r in response.json()["items"]]
        except httpx.RequestError as exc:
            logger.info("data.inclusion request error code_insee=%s error=%s", code_insee, exc)
            raise DataInclusionApiException()
        except KeyError as exc:
            logger.info("data.inclusion result error code_insee=%s error=%s", code_insee, exc)
            raise DataInclusionApiException()
        return []
