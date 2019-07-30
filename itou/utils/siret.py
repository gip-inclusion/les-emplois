import logging
import urllib.request

from api_insee import ApiInsee

from django.conf import settings


logger = logging.getLogger(__name__)


def get_data_for_siret(siret):

    api_insee = ApiInsee(key=settings.API_INSEE_KEY, secret=settings.API_INSEE_SECRET)

    try:
        data = api_insee.siret(siret).get()
    except urllib.error.HTTPError as err:
        logger.error(f"HTTP Error `{err.code}` while calling Sirene - V3 API for SIRET {siret}")
        return None

    if data['header']['statut'] != 200:
        return None

    address = [
        data['etablissement']['adresseEtablissement']['numeroVoieEtablissement'],
        data['etablissement']['adresseEtablissement']['typeVoieEtablissement'],
        data['etablissement']['adresseEtablissement']['libelleVoieEtablissement'],
    ]

    return {
        'name': data['etablissement']['uniteLegale']['denominationUniteLegale'],
        'address': ' '.join(item for item in address if item),
        'zipcode': data['etablissement']['adresseEtablissement']['codePostalEtablissement'],
    }
