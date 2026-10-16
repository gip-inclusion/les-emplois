"""rdv-insertion API dedicated to les emplois."""

import json

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


API_TIMEOUT_SECONDS = 1.0


class RdvInsertionApiError(Exception):
    pass


class RdvInsertionApiClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=API_TIMEOUT_SECONDS,
        )

    def search_user_by_nir(self, nir: str) -> dict | None:
        """Return the rdv-insertion user matching this NIR, or None if there is none or several."""
        try:
            response = self.client.post("users/search", json={"nir": nir})
            # CONFLICT: several users share this NIR, we can't tell if they are the same person
            if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT):
                return None
            return response.raise_for_status().json()["user"]
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise RdvInsertionApiError(f"Error requesting rdv-insertion API: {exc.__class__.__name__}") from exc


def get_client():
    if (
        not settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_BASE_URL
        or not settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN
    ):
        raise ImproperlyConfigured("Missing configuration for rdv-insertion API")
    return RdvInsertionApiClient(
        base_url=settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_BASE_URL,
        token=settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN,
    )
