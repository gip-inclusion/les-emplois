import logging
import re

import httpx
from django.core.cache import cache
from unidecode import unidecode


logger = logging.getLogger(__name__)

API_CLIENT_HTTP_ERROR_CODE = "http_error"
REFRESH_TOKEN_MARGIN_SECONDS = 10  # arbitrary value, in order not to be *right* on the expiry time.


class PoleEmploiAPIException(Exception):
    """unexpected exceptions (meaning, "exceptional") that warrant a subsequent retry."""

    def __init__(self, error_code):
        self.error_code = error_code
        super().__init__()

    def __str__(self):
        return f"PoleEmploiAPIException(code={self.error_code})"


class PoleEmploiAPIBadResponse(Exception):
    """errors that can't be recovered from: the API server does not agree."""

    def __init__(self, response_code):
        self.response_code = response_code
        super().__init__()

    def __str__(self):
        return f"PoleEmploiAPIBadResponse(code={self.response_code})"


class PoleEmploiRateLimitException(PoleEmploiAPIException):
    pass


API_CLIENT_EMPTY_NIR_BAD_RESPONSE = "empty_nir"


API_TIMEOUT_SECONDS = 60  # this API is pretty slow, let's give it a chance

CACHE_API_TOKEN_KEY = "pole_emploi_api_client_token"

# Pole Emploi also sent us a "sandbox" scope value: "api_testmaj-pass-iaev1" instead of "api_maj-pass-iaev1"
AUTHORIZED_SCOPES = [
    "api_maj-pass-iaev1",
    "api_offresdemploiv2",
    "api_rechercheindividucertifiev1",
    "api_romev1",
    "nomenclatureRome",
    "o2dsoffre",
    "passIAE",
    "rechercherIndividuCertifie",
]
API_MAJ_PASS_SUCCESS = "S000"
API_RECH_INDIVIDU_SUCCESS = "S001"
DATE_FORMAT = "%Y-%m-%d"
MAX_NIR_CHARACTERS = 13  # Pole Emploi only cares about the first 13 characters of the NIR.


def _pole_emploi_name(name: str, hyphenate=False, max_len=25) -> str:
    """D’après les specs de l’API PE non documenté concernant la recherche individu
    simplifié, le NOM doit:
     - être en majuscule
     - sans accents (ils doivent être remplacés par l’équivalent non accentué)
     - le tiret, l’espace et l’apostrophe sont acceptés dans les noms
     - sa longueur est max 25 caractères
    Ainsi, "Nôm^' Exémple{}$" devient "NOM EXEMPLE"
    """
    name = unidecode(name).upper()
    if hyphenate:
        name = name.replace(" ", "-")
    replaced = re.sub("[^A-Z-' ]", "", name)
    return replaced[:max_len]


class PoleEmploiApiClient:
    def __init__(self, base_url, auth_base_url, key, secret):
        self.base_url = base_url
        self.auth_base_url = auth_base_url
        self.key = key
        self.secret = secret

    def _refresh_token(self):
        scopes = " ".join(AUTHORIZED_SCOPES)
        response = httpx.post(
            f"{self.auth_base_url}/connexion/oauth2/access_token",
            params={"realm": "/partenaire"},
            data={
                "client_id": self.key,
                "client_secret": self.secret,
                "grant_type": "client_credentials",
                "scope": f"application_{self.key} {scopes}",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        auth_data = response.json()
        token = f"{auth_data['token_type']} {auth_data['access_token']}"
        cache.set(
            CACHE_API_TOKEN_KEY,
            token,
            auth_data["expires_in"]
            - REFRESH_TOKEN_MARGIN_SECONDS,  # make the token expire a little sooner than expected
        )
        return token

    def _request(self, url, data=None, params=None, method="POST"):
        try:
            token = cache.get(CACHE_API_TOKEN_KEY)
            if not token:
                token = self._refresh_token()

            response = httpx.request(
                method,
                url,
                params=params,
                json=data,
                headers={"Authorization": token, "Content-Type": "application/json"},
                timeout=API_TIMEOUT_SECONDS,
            )
            if response.status_code == 204:
                return None
            if response.status_code == 429:
                raise PoleEmploiRateLimitException(429)
            if response.status_code not in (200, 206):
                raise PoleEmploiAPIException(response.status_code)
            data = response.json()
            return data
        except httpx.RequestError as exc:
            raise PoleEmploiAPIException(API_CLIENT_HTTP_ERROR_CODE) from exc

    def recherche_individu_certifie(self, first_name, last_name, birthdate, nir):
        """Example data:
        {
            "nirCertifie":"1800813800217",
            "nomNaissance":"MARTIN",
            "prenom":"LAURENT",
            "dateNaissance":"1979-07-25"
        }

        Example response:
        {
            "idNationalDE":"",
            "codeSortie": "R010",
            "certifDE":false
        }
        """
        data = self._request(
            f"{self.base_url}/rechercheindividucertifie/v1/rechercheIndividuCertifie",
            {
                "dateNaissance": birthdate.strftime(DATE_FORMAT) if birthdate else "",
                "nirCertifie": nir[:MAX_NIR_CHARACTERS] if nir else "",
                "nomNaissance": _pole_emploi_name(last_name),
                "prenom": _pole_emploi_name(first_name, hyphenate=True, max_len=13),
            },
        )
        code_sortie = data.get("codeSortie")
        if code_sortie != API_RECH_INDIVIDU_SUCCESS:
            raise PoleEmploiAPIBadResponse(code_sortie)
        id_national = data.get("idNationalDE")
        if not id_national:
            raise PoleEmploiAPIBadResponse(API_CLIENT_EMPTY_NIR_BAD_RESPONSE)
        return id_national

    def mise_a_jour_pass_iae(
        self, approval, encrypted_identifier, siae_siret, siae_type, origine_candidature, typologie_prescripteur=None
    ):
        """Example of a JSON response:
        {'codeSortie': 'S000', 'idNational': 'some identifier', 'message': 'Pass IAE prescrit'}
        The only valid result is HTTP 200 + codeSortie = "S000".
        Anything else (other HTTP code, or different codeSortie) means that our notification has been discarded.
        """
        params = {
            "dateDebutPassIAE": approval.start_at.strftime(DATE_FORMAT) if approval.start_at else "",
            "dateFinPassIAE": approval.get_pe_end_at(),
            "idNational": encrypted_identifier,
            "numPassIAE": approval.number,
            # we force this field to be "A" for "Approved". The origin of this field is lost with
            # the first iterations of this client, but our guess is that it makes their server happy.
            # this has no impact on our side since a PASS IAE is always "approved", even though it might be suspended.
            # Maybe some day we will support this case and send them our suspended PASS IAE if needed.
            "statutReponsePassIAE": "A",
            "numSIRETsiae": siae_siret,
            "typeSIAE": siae_type,
            "origineCandidature": origine_candidature,
        }
        if typologie_prescripteur is not None:
            params["typologiePrescripteur"] = typologie_prescripteur
        data = self._request(f"{self.base_url}/maj-pass-iae/v1/passIAE/miseAjour", params)
        code_sortie = data.get("codeSortie")
        if code_sortie != API_MAJ_PASS_SUCCESS:
            raise PoleEmploiAPIBadResponse(code_sortie)

    def referentiel(self, code):
        return self._request(f"{self.base_url}/offresdemploi/v2/referentiel/{code}", method="GET")

    def offres(self, typeContrat="", natureContrat="", range=None):
        params = {"typeContrat": typeContrat, "natureContrat": natureContrat}
        if range:
            params["range"] = range
        data = self._request(f"{self.base_url}/offresdemploi/v2/offres/search", params=params, method="GET")
        if not data:
            return []
        return data["resultats"]

    def appellations(self):
        return self._request(f"{self.base_url}/rome/v1/appellation?champs=code,libelle,metier(code)", method="GET")
