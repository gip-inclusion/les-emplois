import dataclasses
import logging

import httpx


logger = logging.getLogger(__name__)


class DataInclusionApiException(Exception):
    pass


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class DataInclusionApiPaginatedResponse:
    items: list[dict]
    total: int
    page: int
    size: int
    pages: int


class DataInclusionApiItemsIterator:
    DEFAULT_PAGE = 1
    DEFAULT_PAGE_SIZE = 5_000

    def __init__(self, client_method, *, page_size=DEFAULT_PAGE_SIZE, params=None):
        self._client_method = client_method
        self._params = params or {}
        self.page_size = page_size

    def __iter__(self):
        page = self.DEFAULT_PAGE
        # This is a workaround since data⋅inclusion uses an offset-based pagination
        # that might change the order and IDs in a page between 2 calls. Fixing it
        # using cursor pagination or a client-controlled ordering is not on the table
        # yet; data⋅inclusion might even deprecate these endpoints and use parquet
        # flat files instead. Anyway, we 'fix' it on the iterator side, making gaps and
        # duplicates disappear.
        seen_ids = set()
        while True:
            response = self._client_method(**{**self._params, "page": page, "size": self.page_size})
            for item in response.items:
                if item["id"] in seen_ids:
                    continue  # duplicate detected between 2 pages
                seen_ids.add(item["id"])
                yield item
            if response.page >= response.pages:
                break
            page += 1


class DataInclusionApiClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1/",
            headers={"Authorization": f"Bearer {token}"},
        )

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, type, value, traceback):
        self.client.__exit__(type, value, traceback)

    def _request(self, route, params, *, method="GET"):
        try:
            response = self.client.request(
                method, route, params=params, timeout=httpx.Timeout(5, read=60)
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("data.inclusion request error params=%r error=%s", params, exc)
            raise DataInclusionApiException()

        return response

    def search_services(self, **params) -> list[dict]:
        response = self._request("/search/services", params)
        try:
            return [r["service"] for r in response.json()["items"]]
        except KeyError as exc:
            logger.info("data.inclusion result error params=%r error=%s", params, exc)
            raise DataInclusionApiException()

    def services(self, **params) -> DataInclusionApiPaginatedResponse:
        return DataInclusionApiPaginatedResponse(**self._request("/services", params).json())

    def sources(self, **params):
        return self._request("/sources", params).json()

    def structures(self, **params) -> DataInclusionApiPaginatedResponse:
        return DataInclusionApiPaginatedResponse(**self._request("/structures", params).json())

    def doc(self, kind, **params) -> list[dict]:
        return self._request(f"/doc/{kind}", params).json()

    def search_sps_services(self, *, code_commune: str) -> list[dict]:
        """Return SPS services for a given INSEE city code.

        Fetches in-person, free services from DORA and filters on the SPS networks
        (reseaux_porteurs), which is not a supported query param on the API side (yet).
        """

        services = self.search_services(
            code_commune=code_commune,
            sources=["dora"],  # filter applied on services DI-sides
            modes_accueil=["en-presentiel"],  # filter applied on structures DI-side
            frais=["gratuit"],  # filter applied on services DI-sides
        )

        # Networks qualifying as structured pathway solutions (SPS / solutions de parcours structurées)
        sps_networks = {
            "epide",
            "ecoles-de-la-deuxieme-chance",
            "plie",
            "alliance-villes-emploi",
            "apprentis-dauteuil",
        }
        return [s for s in services if sps_networks & set(s["structure"].get("reseaux_porteurs") or [])]
