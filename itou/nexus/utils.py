import json
import logging
import time

from django.conf import settings
from jwcrypto import jwk, jwt

from itou.nexus.enums import Service


logger = logging.getLogger(__name__)

KEY = jwk.JWK(**settings.NEXUS_AUTO_LOGIN_KEY) if settings.NEXUS_AUTO_LOGIN_KEY else None
EXPIRY_DELAY = 60  # seconds


def generate_jwt(user):
    token = jwt.JWT(
        header={"alg": "A256KW", "enc": "A256CBC-HS512"},
        claims={"email": user.email, "exp": round(time.time()) + EXPIRY_DELAY},
    )
    token.make_encrypted_token(KEY)
    return token.serialize()


def decode_jwt(token):
    try:
        claims = json.loads(jwt.JWT(key=KEY, jwt=token, expected_type="JWE").claims)
        claims.pop("exp", None)
        return claims
    except Exception:
        logger.exception("Could not decrypt jwt")
        raise ValueError


SERVICE_MAPPING = {
    Service.COMMUNAUTE: "la-communauté",
    Service.DORA: "dora",
    Service.EMPLOIS: "emplois-de-linclusion",
    Service.MARCHE: "le-marché",
    Service.DATA_INCLUSION: "data-inclusion",
    Service.PILOTAGE: "pilotage",
    Service.MON_RECAP: "mon-recap",
}


def service_id(id, service):
    return f"{SERVICE_MAPPING[service]}--{id}"
