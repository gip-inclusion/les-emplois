import logging

import requests
from django.conf import settings
from django.utils.http import urlencode

from itou.utils.address.departments import department_from_postcode


logger = logging.getLogger(__name__)


def etablissements(siret, object="Inscription à la Plateforme de l'inclusion"):
    """
    https://doc.entreprise.api.gouv.fr/?json#etablissements-v2
    """

    api_url = f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}"

    args = {
        "recipient": settings.API_ENTREPRISE_RECIPIENT,
        "context": settings.API_ENTREPRISE_CONTEXT,
        "object": object,
    }
    query_string = urlencode(args)

    headers = {"Authorization": f"Bearer {settings.API_ENTREPRISE_TOKEN}"}

    url = f"{api_url}?{query_string}"

    try:
        r = requests.get(url, headers=headers)
    except requests.exceptions.RequestException as e:
        logger.error("Error while fetching `%s`: %s", url, e)
        return None

    response = r.json()

    return {
        "name": response["etablissement"]["adresse"]["l1"],
        "address_line_1": response["etablissement"]["adresse"]["l4"],
        "address_line_2": response["etablissement"]["adresse"]["l3"],
        "post_code": response["etablissement"]["adresse"]["code_postal"],
        "city": response["etablissement"]["adresse"]["localite"],
        "department": department_from_postcode(post_code),
    }
