import logging

import requests
from django.conf import settings
from django.utils.http import urlencode

from itou.utils.address.departments import department_from_postcode


logger = logging.getLogger(__name__)


class Etablissement:
    """
    https://doc.entreprise.api.gouv.fr/?json#etablissements-v2
    """

    def __init__(self, siret, object="Inscription à la Plateforme de l'inclusion"):

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

        self.data = r.json()

    @property
    def name(self):
        return self.data["etablissement"]["adresse"]["l1"]

    @property
    def address(self):
        post_code = self.data["etablissement"]["adresse"]["code_postal"]
        department = department_from_postcode(post_code)
        return {
            "address_line_1": self.data["etablissement"]["adresse"]["l4"],
            "address_line_2": self.data["etablissement"]["adresse"]["l3"],
            "post_code": post_code,
            "city": self.data["etablissement"]["adresse"]["localite"],
            "department": department,
        }
