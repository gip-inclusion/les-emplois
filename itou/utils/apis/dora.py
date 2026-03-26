import logging

import httpx


logger = logging.getLogger(__name__)


class DoraAPIException(Exception):
    pass


class DoraAPIClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/emplois/",
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
        return {
            "dora--" + r["id"]: {**r, "uid": "dora--" + r["id"]}
            for r in self._request("/services/", params).json()
        }

    def disabled_dora_form_di_structures(self, **params):
        return {
            r["source"] + "--" + r["structure_id"]
            for r in self._request("/disabled-dora-form-di-structures/", params).json()
        }
