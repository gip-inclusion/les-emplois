import datetime
import json
import logging
import re
import time

import httpx
from django.core.cache import caches
from unidecode import unidecode


logger = logging.getLogger(__name__)

API_CLIENT_HTTP_ERROR_CODE = "http_error"
REFRESH_TOKEN_MARGIN_SECONDS = 10  # arbitrary value, in order not to be *right* on the expiry time.

# Source:
# https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation#/api-reference/operations/recupererListeOffre
OFFERS_MIN_INDEX = 0
OFFERS_MAX_INDEX = 3149
OFFERS_MAX_RANGE = 150


class PoleEmploiAPIException(Exception):
    """unexpected exceptions (meaning, "exceptional") that warrant a subsequent retry."""

    def __init__(self, error_code, response_content=None):
        self.error_code = error_code
        self.response_content = response_content
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


class BasePoleEmploiApiClient:
    AUTHORIZED_SCOPES = []
    REALM = ""
    CACHE_API_TOKEN_KEY = ""

    def __init__(self, base_url, auth_base_url, key, secret):
        if not self.AUTHORIZED_SCOPES:
            raise NotImplementedError("Authorized scopes missing.")
        if not self.REALM:
            raise NotImplementedError("Realm missing.")
        if not self.CACHE_API_TOKEN_KEY:
            raise NotImplementedError("Cache key missing.")
        self.base_url = base_url
        self.auth_base_url = auth_base_url
        self.key = key
        self.secret = secret

    def _refresh_token(self):
        scopes = " ".join(self.AUTHORIZED_SCOPES)
        auth_data = (
            httpx.post(
                f"{self.auth_base_url}/connexion/oauth2/access_token",
                params={"realm": self.REALM},
                data={
                    "client_id": self.key,
                    "client_secret": self.secret,
                    "grant_type": "client_credentials",
                    "scope": f"application_{self.key} {scopes}",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            .raise_for_status()
            .json()
        )
        token = f"{auth_data['token_type']} {auth_data['access_token']}"
        caches["failsafe"].set(
            self.CACHE_API_TOKEN_KEY,
            token,
            auth_data["expires_in"]
            - REFRESH_TOKEN_MARGIN_SECONDS,  # make the token expire a little sooner than expected
        )
        return token

    def _request(self, url, data=None, params=None, method="POST"):
        try:
            token = caches["failsafe"].get(self.CACHE_API_TOKEN_KEY)
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
                logger.warning("Request on url=%s triggered rate limit", url)
                raise PoleEmploiRateLimitException(429)
            if response.status_code not in (200, 206):
                logger.warning("Request on url=%s returned status_code=%s", url, response.status_code)
                try:
                    content = response.json()
                    # This might look like:
                    # {'codeErreur': 'JCS0011G', 'codeHttp': 500,
                    #  'message': 'La vue service retournée par le connecteur HTTP est nulle ou mal formée'}
                except json.decoder.JSONDecodeError:
                    content = response.content
                raise PoleEmploiAPIException(response.status_code, response_content=content)
            data = response.json()
            return data
        except httpx.RequestError as exc:
            raise PoleEmploiAPIException(API_CLIENT_HTTP_ERROR_CODE) from exc


class PoleEmploiRoyaumePartenaireApiClient(BasePoleEmploiApiClient):
    # Pole Emploi also sent us a "sandbox" scope value: "api_testmaj-pass-iaev1" instead of "api_maj-pass-iaev1"
    AUTHORIZED_SCOPES = [
        "api_maj-pass-iaev1",
        "api_offresdemploiv2",
        "api_rechercheindividucertifiev1",
        "api_rome-metiersv1",
        "nomenclatureRome",
        "o2dsoffre",
        "passIAE",
        "rechercherIndividuCertifie",
        "api_referentielagencesv1",
        "organisationpe",
    ]
    REALM = "/partenaire"
    CACHE_API_TOKEN_KEY = "pole_emploi_api_partenaire_client_token"

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
            "dateDebutPassIAE": approval.start_at.strftime(DATE_FORMAT),
            "dateFinPassIAE": approval.get_pe_end_at(),
            "idNational": encrypted_identifier,
            "numPassIAE": approval.number,
            # we force this field to be "A" for "Approved". The origin of this field is lost with
            # the first iterations of this client, but our guess is that it makes their server happy.
            # this has no impact on our side since a PASS IAE is always "approved", even though it might be suspended.
            # Maybe some day we will support this case and send them our suspended PASS IAE if needed.
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

    def retrieve_all_offres(self, typeContrat="", natureContrat="", *, delay_between_requests=datetime.timedelta(0)):
        # NOTE: using this unfiltered API we can only sync at most OFFERS_MAX_RANGE offers.
        # If someday there are more offers, we will need to setup a much more complicated sync mechanism, for instance
        # by requesting every department one by one. But so far we are not even close from half this quota.
        raw_offers = []
        for i in range(OFFERS_MIN_INDEX, OFFERS_MAX_INDEX, OFFERS_MAX_RANGE):
            max_range = min(OFFERS_MAX_INDEX, i + OFFERS_MAX_RANGE - 1)
            offers = self.offres(typeContrat=typeContrat, natureContrat=natureContrat, range=f"{i}-{max_range}")
            logger.info(f"retrieved count={len(offers)} offers from FT API")
            if not offers:
                break
            raw_offers.extend(offers)
            if max_range == OFFERS_MAX_INDEX and len(offers) == OFFERS_MAX_RANGE:
                logger.error("FT API returned the maximum number of offers: some offers are likely missing")

            time.sleep(delay_between_requests.total_seconds())
        return raw_offers

    def appellations(self):
        return self._request(
            f"{self.base_url}/rome-metiers/v1/metiers/appellation?champs=code,libelle,metier(code)",
            method="GET",
        )

    def agences(self, safir=None):
        agences = self._request(f"{self.base_url}/referentielagences/v1/agences", method="GET")
        if safir:
            return next((agence for agence in agences if agence["codeSafir"] == str(safir)), None)
        return agences


class PoleEmploiRoyaumeAgentAPIClient(BasePoleEmploiApiClient):
    AUTHORIZED_SCOPES = [
        "api_rechercher-usagerv2",
        "rechercheusager",
        "profil_accedant",
        "api_donnees-rqthv1",
        "h2a",
    ]
    REALM = "/agent"
    CACHE_API_TOKEN_KEY = "pole_emploi_api_agent_client_token"
