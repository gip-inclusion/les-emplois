import logging
from urllib.parse import urljoin

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from .enums import InvitationStatus


logger = logging.getLogger(__name__)


RDV_S_CREDENTIALS_CACHE_KEY = "rdv-solidarites-credentials"

RDV_I_INVITATION_DELIVERED_STATUSES = ["delivered"]
RDV_I_INVITATION_NOT_DELIVERED_STATUSES = ["soft_bounce", "hard_bounce", "blocked", "invalid_email", "error"]


def get_api_credentials(refresh=False):
    """
    RDV-I and RDV-S APIs share the same userbase and credentials.
    Their tokens are issued for a 24h period and each renewal invalidates anterior tokens.
    The credentials are cached and automatically refreshed using this function.
    """
    if settings.RDV_SOLIDARITES_API_BASE_URL and settings.RDV_SOLIDARITES_EMAIL and settings.RDV_SOLIDARITES_PASSWORD:
        with cache.lock("rdv-solidarites-credentials-lock", blocking_timeout=10):
            if refresh or not (api_credentials := cache.get(RDV_S_CREDENTIALS_CACHE_KEY)):
                response = httpx.post(
                    urljoin(settings.RDV_SOLIDARITES_API_BASE_URL, "auth/sign_in"),
                    data={
                        "email": settings.RDV_SOLIDARITES_EMAIL,
                        "password": settings.RDV_SOLIDARITES_PASSWORD,
                    },
                )
                response.raise_for_status()
                api_credentials = {
                    "access-token": response.headers["access-token"],
                    "client": response.headers["client"],
                    "uid": response.headers["uid"],
                }
                cache.set(RDV_S_CREDENTIALS_CACHE_KEY, api_credentials, settings.RDV_SOLIDARITES_TOKEN_EXPIRY)
            return api_credentials

    raise ImproperlyConfigured(
        "RDV-S settings must be set: RDV_SOLIDARITES_API_BASE_URL, RDV_SOLIDARITES_EMAIL, RDV_SOLIDARITES_PASSWORD"
    )


def get_invitation_status(invitation_dict):
    if invitation_dict.get("clicked"):
        return InvitationStatus.OPENED
    if delivery_status := invitation_dict.get("delivery_status"):
        if delivery_status in RDV_I_INVITATION_DELIVERED_STATUSES:
            return InvitationStatus.DELIVERED
        if delivery_status in RDV_I_INVITATION_NOT_DELIVERED_STATUSES:
            return InvitationStatus.NOT_DELIVERED
        logger.error(f"Invalid RDV-I invitation status: '{delivery_status}' not in supported list")
