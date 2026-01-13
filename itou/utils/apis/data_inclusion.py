import logging

import httpx


logger = logging.getLogger(__name__)


class DataInclusionApiException(Exception):
    pass


class DataInclusionApiV1Client:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1/",
            headers={"Authorization": f"Bearer {token}"},
        )

    def search_services(self, **params) -> list[dict]:
        try:
            response = self.client.get(
                "/search/services",
                params=params,
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("data.inclusion request error params=%r error=%s", params, exc)
            raise DataInclusionApiException()

        try:
            return [r["service"] for r in response.json()["items"]]
        except KeyError as exc:
            logger.info("data.inclusion result error params=%r error=%s", params, exc)
            raise DataInclusionApiException()
