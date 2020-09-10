import logging

import requests
from django.conf import settings
from django.utils.http import urlencode
from django.utils.translation import gettext as _, gettext_lazy

from itou.utils.address.departments import department_from_postcode


logger = logging.getLogger(__name__)


class EtablissementAPI:
    """
    https://doc.entreprise.api.gouv.fr/?json#etablissements-v2
    """

    ERROR_IS_CLOSED = gettext_lazy("La base Sirene indique que l'état administratif de l'établissement est fermé.")

    def __init__(self, siret, object="Inscription à la Plateforme de l'inclusion"):
        self.data, self.error = self.get(siret, object)

    def get(self, siret, object):

        data = None
        error = None

        query_string = urlencode(
            {
                "recipient": settings.API_ENTREPRISE_RECIPIENT,
                "context": settings.API_ENTREPRISE_CONTEXT,
                "object": object,
            }
        )

        url = f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}?{query_string}"
        headers = {"Authorization": f"Bearer {settings.API_ENTREPRISE_TOKEN}"}

        try:
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 422:
                error = _("SIRET non reconnu.")
            else:
                logger.error("Error while fetching `%s`: %s", url, e)
                error = _("Problème de connexion à la base Sirene. Veuillez réessayer ultérieurement.")

        if data and data.get("errors"):
            error = data["errors"][0]

        return data, error

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

    @property
    def is_closed(self):
        return self.data["etablissement"]["etat_administratif"]["value"] == "F"
