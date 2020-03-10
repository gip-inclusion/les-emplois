import collections
import datetime
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

Token = collections.namedtuple("AccessToken", ["expiration", "value"])

TOKENS_CACHE = {}


def get_access_token(scope):

    if scope in TOKENS_CACHE:
        token = TOKENS_CACHE[scope]
        now = datetime.datetime.now()
        if now < token.expiration:
            logger.debug(
                "Found %s in cache. Expiration = %s, now = %s.",
                token.value,
                token.expiration,
                now,
            )
            return token.value

    auth_request = requests.post(
        f"{settings.API_EMPLOI_STORE_AUTH_BASE_URL}/connexion/oauth2/access_token",
        data={
            "realm": "/partenaire",
            "grant_type": "client_credentials",
            "client_id": settings.API_EMPLOI_STORE_KEY,
            "client_secret": settings.API_EMPLOI_STORE_SECRET,
            "scope": f"application_{settings.API_EMPLOI_STORE_KEY} {scope}",
        },
    )
    auth_request.raise_for_status()

    r = auth_request.json()
    value = f"{r['token_type']} {r['access_token']}"
    expiration = datetime.datetime.now() + datetime.timedelta(seconds=r["expires_in"])
    token = Token(value=value, expiration=expiration)
    TOKENS_CACHE[scope] = token
    return token.value
