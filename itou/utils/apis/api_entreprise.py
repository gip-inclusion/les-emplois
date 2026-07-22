import datetime
import json
import logging
from dataclasses import dataclass

import httpx
import jwt
from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from itou.common_apps.address.departments import department_from_postcode
from itou.utils.slack import send_slack_message


logger = logging.getLogger(__name__)

INSEE_EXPIRY_ALREADY_NOTIFIED_CACHE_KEY = "INSEE_EXPIRY_ALREADY_NOTIFIED"


def check_and_warn_password_renewal(access_token):
    cache = caches["failsafe"]
    if cache.get(INSEE_EXPIRY_ALREADY_NOTIFIED_CACHE_KEY):
        return
    # The documentation does not explain where to retrieve the public key required to check the jwt signature
    token_content = jwt.decode(access_token, options={"verify_signature": False})
    password_changed_date = timezone.localdate(
        datetime.datetime.strptime(token_content["pwdChangedTime"], "%Y%m%d%H%M%S%z")
    )
    expiry_date = password_changed_date + datetime.timedelta(days=90)
    if timezone.localdate() >= expiry_date - datetime.timedelta(days=15):
        send_slack_message(
            f"Le mot de passe INSEE va expirer le {expiry_date}, "
            "merci de le modifier sur https://portail-api.insee.fr et "
            "de le changer dans les settings (API_INSEE_PASSWORD)",
        )
    cache.set(INSEE_EXPIRY_ALREADY_NOTIFIED_CACHE_KEY, True, timeout=60 * 60 * 24)  # Skip for one day


@dataclass
class Etablissement:
    name: str
    address_line_1: str
    address_line_2: str
    post_code: str
    city: str
    department: str
    is_head_office: bool
    is_closed: bool


def get_access_token():
    try:
        access_token = (
            httpx.post(
                f"{settings.API_INSEE_AUTH_URL}/token",
                data={
                    "grant_type": "password",
                    "client_id": settings.API_INSEE_CLIENT_ID,
                    "client_secret": settings.API_INSEE_CLIENT_SECRET,
                    "username": settings.API_INSEE_USERNAME,
                    "password": settings.API_INSEE_PASSWORD,
                },
            )
            .raise_for_status()
            .json()["access_token"]
        )
    except Exception:
        logger.exception("Failed to retrieve an access token")
        return None
    else:
        check_and_warn_password_renewal(access_token)
        return access_token


def etablissement_get_or_error(siret):
    """
    Return a tuple (etablissement, error) where error is None on success.
    https://portail-api.insee.fr/catalog/api/2ba0e549-5587-3ef1-9082-99cd865de66f/doc
    """

    access_token = get_access_token()
    if not access_token:
        return None, "Problème de connexion à la base Sirene. Essayez ultérieurement."

    url = f"{settings.API_INSEE_SIRENE_URL}/siret/{siret}"
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        ).raise_for_status()
    except httpx.RequestError:
        logger.exception("A request to the INSEE API failed")
        return None, "Problème de connexion à la base Sirene. Essayez ultérieurement."
    except httpx.HTTPStatusError as e:
        if e.response.status_code == httpx.codes.BAD_REQUEST:
            error = f"Erreur dans le format du SIRET : « {siret} »."
        elif e.response.status_code == httpx.codes.FORBIDDEN:
            error = "Cette entreprise a exercé son droit d'opposition auprès de l'INSEE."
        elif e.response.status_code == httpx.codes.NOT_FOUND:
            error = f"SIRET « {siret} » non reconnu."
        else:
            logger.error("Error while fetching `%s`: %s", url, e)
            error = "Problème de connexion à la base Sirene. Essayez ultérieurement."
        return None, error

    try:
        data = r.json()
        name = data["etablissement"]["uniteLegale"]["denominationUniteLegale"]
        address = data["etablissement"]["adresseEtablissement"]
        address_parts = [
            address["numeroVoieEtablissement"],
            address["typeVoieEtablissement"],
            address["libelleVoieEtablissement"],
        ]
        post_code = address["codePostalEtablissement"]
        city = address["libelleCommuneEtablissement"]
        establishments_status = data["etablissement"]["periodesEtablissement"][0]["etatAdministratifEtablissement"]
        is_head_office = data["etablissement"]["etablissementSiege"]
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.exception("Invalid format of response from API Entreprise")
        return None, "Le format de la réponse API Entreprise est non valide."

    etablissement = Etablissement(
        name=name,
        address_line_1=" ".join(filter(None, address_parts)) or None,
        address_line_2=address.get("complementAdresseEtablissement"),
        post_code=post_code,
        city=city,
        department=department_from_postcode(post_code) or None,
        is_closed=(establishments_status == "F"),
        is_head_office=is_head_office,
    )

    return etablissement, None
