import logging
import urllib.request

from api_insee import ApiInsee

from django.conf import settings


logger = logging.getLogger(__name__)


def call_insee_api(siret):

    api_insee = ApiInsee(key=settings.API_INSEE_KEY, secret=settings.API_INSEE_SECRET)

    try:
        data = api_insee.siret(siret).get()
    except urllib.error.HTTPError as err:
        logger.error(f"HTTP Error `{err.code}` while calling Sirene - V3 API for SIRET {siret}")
        return None

    return data


def process_siret_data(data):

    if not data:
        return None

    try:
        address = [
            data['etablissement']['adresseEtablissement']['numeroVoieEtablissement'],
            data['etablissement']['adresseEtablissement']['typeVoieEtablissement'],
            data['etablissement']['adresseEtablissement']['libelleVoieEtablissement'],
        ]
        return {
            'name': data['etablissement']['uniteLegale']['denominationUniteLegale'],
            'address': ' '.join(item for item in address if item),
            'post_code': data['etablissement']['adresseEtablissement']['codePostalEtablissement'],
        }
    except KeyError:
        logger.error(f"Unable to process the result of Sirene V3 API: {data}")
        return None


def get_siret_data(siret):

    siret_data = call_insee_api(siret)

    return process_siret_data(siret_data)
