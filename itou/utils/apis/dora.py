import logging

import httpx


logger = logging.getLogger(__name__)


class DoraAPIException(Exception):
    pass


class DoraAPIClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/",
            # headers={"Authorization": f"Token {token}"},  # FIXME
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

    def emplois_services(self, **params):
        return self._request("/emplois/services/", params).json()

    def disabled_dora_form_di_structures(self, **params):
        return {
            r["source"] + "--" + r["structure_id"]
            for r in self._request("/emplois/disabled-dora-form-di-structures/", params).json()
        }
