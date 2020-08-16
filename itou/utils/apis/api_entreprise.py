import logging

import requests
from django.conf import settings
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from itou.utils.address.departments import department_from_postcode


logger = logging.getLogger(__name__)


class EtablissementAPI:
    """
    https://doc.entreprise.api.gouv.fr/?json#etablissements-v2
    """

    def __init__(self, siret, object="Inscription à la Plateforme de l'inclusion"):

        self.error = None

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
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error("Error while fetching `%s`: %s", url, e)
            self.error = _("Erreur de connexion à API Entreprise.")
            return

        r = requests.get(url, headers=headers)
        self.data = r.json()

        if self.data.get("errors"):
            self.error = self.data["errors"][0]

    @property
    def name(self):
        return self.data["etablissement"]["adresse"]["l1"]

    @property
    def address_line_1(self):
        return self.data["etablissement"]["adresse"]["l4"]

    @property
    def address_line_2(self):
        return self.data["etablissement"]["adresse"]["l3"]

    @property
    def post_code(self):
        return self.data["etablissement"]["adresse"]["code_postal"]

    @property
    def city(self):
        return self.data["etablissement"]["adresse"]["localite"]

    @property
    def department(self):
        return department_from_postcode(self.post_code)
