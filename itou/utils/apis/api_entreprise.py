import logging
from dataclasses import dataclass

import httpx
from django.conf import settings
from django.utils.http import urlencode

from itou.utils.address.departments import department_from_postcode


logger = logging.getLogger(__name__)


@dataclass
class Etablissement:
    name: str
    address_line_1: str
    address_line_2: str
    post_code: str
    city: str
    department: str
    is_closed: bool


def etablissement_get_or_error(siret, reason="Inscription aux emplois de l'inclusion"):
    """
    Return a tuple (etablissement, error) where error is None on success.
    https://doc.entreprise.api.gouv.fr/?json#etablissements-v2
    """
    data = None
    etablissement = None
    error = None

    query_string = urlencode(
        {
            "recipient": settings.API_ENTREPRISE_RECIPIENT,
            "context": settings.API_ENTREPRISE_CONTEXT,
            "object": reason,
        }
    )

    url = f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}?{query_string}"
    headers = {"Authorization": f"Bearer {settings.API_ENTREPRISE_TOKEN}"}

    try:
        r = httpx.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 422:
            error = f"SIRET « {siret} » non reconnu."
        else:
            logger.error("Error while fetching `%s`: %s", url, e)
            error = "Problème de connexion à la base Sirene. Essayez ultérieurement."
        return None, error

    if data and data.get("errors"):
        error = data["errors"][0]
        return None, error

    if not data.get("etablissement") or not data["etablissement"].get("adresse"):
        logger.error("Invalid format of response from API Entreprise")
        error = "Le format de la réponse API Entreprise est non valide."
        return None, error

    address = data["etablissement"]["adresse"]
    etablissement = Etablissement(
        name=address["l1"],
        # FIXME To check (l4 => line_1)
        address_line_1=address["l4"],
        address_line_2=address["l3"],
        post_code=address["code_postal"],
        city=address["localite"],
        department=department_from_postcode(address["code_postal"]),
        is_closed=data["etablissement"]["etat_administratif"]["value"] == "F",
    )

    return etablissement, None
