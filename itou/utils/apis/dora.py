import dataclasses
import logging
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)


class DoraAPIException(Exception):
    pass


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class DoraApiPaginatedResponse:
    results: list[dict]
    count: int
    next: str | None
    previous: str | None


class DoraApiItemsIterator:
    DEFAULT_PAGE = 1
    DEFAULT_PAGE_SIZE = 1_000

    def __init__(self, client_method, *, page_size=DEFAULT_PAGE_SIZE, params=None):
        self._client_method = client_method
        self._params = params or {}
        self.page_size = page_size

    def __iter__(self):
        page = self.DEFAULT_PAGE
        while True:
            response = self._client_method(**{**self._params, "page": page, "page_size": self.page_size})
            yield from response.results
            if response.next is None:
                break
            page += 1


class DoraAPIClient:
    def __init__(self, base_url: str, token: str):
        self._base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self._base_url + "/api/emplois/",
            headers={"Authorization": f"Token {token}"},
        )

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, type, value, traceback):
        self.client.__exit__(type, value, traceback)

    def _request(self, url, params, *, method="GET"):
        try:
            response = self.client.request(
                method,
                url,
                params=params,
                timeout=httpx.Timeout(5, read=60),
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("DORA request error params=%r error=%s", params, exc)
            raise DoraAPIException()

        return response

    def reference_data(self, **params):
        return self._request("/reference-data/", params).json()

    def emplois_services(self, **params):
        return DoraApiPaginatedResponse(**self._request("/services/", params).json())

    def disabled_dora_form_di_structures(self, **params):
        return {
            r["source"] + "--" + r["structure_id"]
            for r in self._request("/disabled-dora-form-di-structures/", params).json()
        }

    def safe_upload(self, file_name: str, file_obj: object) -> dict:
        try:
            response = self.client.post(
                f"{self._base_url}/safe-upload/{quote(file_name)}/",
                files={"file": file_obj},
                timeout=httpx.Timeout(5, read=60),
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("DORA safe-upload error file_name=%r error=%s", file_name, exc)
            raise DoraAPIException()
        upload_response = response.json()
        logger.info("DORA safe-upload success file_name=%r key=%s", file_name, upload_response.get("key"))
        return upload_response

    def create_orientation(self, payload: dict) -> dict:
        try:
            response = self.client.post(
                "/orientations/",
                json=payload,
                timeout=httpx.Timeout(5, read=60),
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.info(
                "DORA create-orientation error di_service_id=%r error=%s",
                payload.get("di_service_id"),
                exc,
            )
            raise DoraAPIException()
        orientation_response = response.json()
        logger.info(
            "DORA create-orientation success di_service_id=%r orientation_id=%s",
            payload.get("di_service_id"),
            orientation_response.get("id"),
        )
        return orientation_response
