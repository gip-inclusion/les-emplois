import json
import logging
from dataclasses import dataclass

import httpx
from django.conf import settings
from django.utils import timezone

from itou.common_apps.address.departments import department_from_postcode


logger = logging.getLogger(__name__)


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
                f"{settings.API_INSEE_BASE_URL}/token",
                data={"grant_type": "client_credentials"},
                auth=(settings.API_INSEE_CONSUMER_KEY, settings.API_INSEE_CONSUMER_SECRET),
            )
            .raise_for_status()
            .json()["access_token"]
        )
    except Exception:
        logger.exception("Failed to retrieve an access token")
        return None
    else:
        return access_token


def etablissement_get_or_error(siret):
    """
    Return a tuple (etablissement, error) where error is None on success.
    https://www.sirene.fr/static-resources/htm/siret_unitaire_variables_reponse.html
    """

    access_token = get_access_token()
    if not access_token:
        return None, "Problème de connexion à la base Sirene. Essayez ultérieurement."

    url = f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/{siret}"
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"date": timezone.localdate().isoformat()},
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
