import collections
import datetime
import logging
import os

import requests

from django.conf import settings


logger = logging.getLogger(__name__)

Token = collections.namedtuple('AccessToken', ['expiration', 'value'])

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

TOKENS_CACHE = {}


def get_access_token(scope):

    if scope in TOKENS_CACHE:
        token = TOKENS_CACHE[scope]
        now = datetime.datetime.now()
        if now < token.expiration:
            logger.debug(f"Found {token.value} in cache. Expiration = {token.expiration}, now = {now}.")
            return token.value

    auth_request = requests.post(
        'https://entreprise.pole-emploi.fr/connexion/oauth2/access_token',
        data={
            'realm': '/partenaire',
            'grant_type': 'client_credentials',
            'client_id': settings.API_EMPLOI_STORE_KEY,
            'client_secret': settings.API_EMPLOI_STORE_SECRET,
            'scope': f'application_{settings.API_EMPLOI_STORE_KEY} {scope}',
        })
    auth_request.raise_for_status()

    r = auth_request.json()
    value = f"{r['token_type']} {r['access_token']}"
    expiration = datetime.datetime.now() + datetime.timedelta(seconds=r['expires_in'])
    token = Token(value=value, expiration=expiration)
    TOKENS_CACHE[scope] = token
    return token.value


def generate_rome_appellations():

    token = get_access_token('api_romev1 nomenclatureRome')

    r = requests.get(
        'https://api.emploi-store.fr/partenaire/rome/v1/appellation',
        headers={'Authorization': token},
    )
    r.raise_for_status()

    file_path = f"{CURRENT_DIR}/rome_appellations.json"
    with open(file_path, 'wb') as f:
        f.write(r.content)

    logger.debug("Done.")
