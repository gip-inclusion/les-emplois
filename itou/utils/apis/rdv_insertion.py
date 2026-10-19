"""rdv-insertion API dedicated to les emplois."""

import datetime
import json
import logging

import httpx
from django.conf import settings
from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured


logger = logging.getLogger(__name__)

API_TIMEOUT_SECONDS = 1.0
CACHE_TIMEOUT_FOUND = datetime.timedelta(hours=1).total_seconds()
CACHE_TIMEOUT_NOT_FOUND = datetime.timedelta(days=1).total_seconds()
# While set, rdv-insertion is not called so that pages don't wait for its timeout
UNAVAILABLE_CACHE_KEY = "rdv-insertion-unavailable"
UNAVAILABLE_CACHE_TIMEOUT = datetime.timedelta(minutes=1).total_seconds()


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


def get_follow_ups(job_seeker):
    """The job seeker's rdv-insertion follow-ups, or [] if they can't be fetched.

    A follow-up is the job seeker's journey in a motif category (e.g. "RSA orientation"), with its participations.
    """
    cache = caches["failsafe"]
    cache_key = f"rdv-insertion-follow-ups:{job_seeker.pk}"
    if (follow_ups := cache.get(cache_key)) is not None:
        return follow_ups
    nir = job_seeker.jobseeker_profile.nir
    if not nir or cache.get(UNAVAILABLE_CACHE_KEY):
        return []
    try:
        user = get_client().search_user_by_nir(nir)
    except ImproperlyConfigured:
        return []
    except RdvInsertionApiError as exc:
        logger.warning("rdv-insertion is unavailable: %s", exc)
        cache.set(UNAVAILABLE_CACHE_KEY, True, UNAVAILABLE_CACHE_TIMEOUT)
        return []
    follow_ups = user["follow_ups"] if user else []
    cache.set(cache_key, follow_ups, CACHE_TIMEOUT_FOUND if user else CACHE_TIMEOUT_NOT_FOUND)
    return follow_ups
