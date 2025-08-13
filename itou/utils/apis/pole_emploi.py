import datetime
import json
import logging
import re
import time

import httpx
from django.conf import settings
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

    def __init__(self, error_code=None, response_content=None):
        self.error_code = error_code
        self.response_content = response_content
        super().__init__()

    def __str__(self):
        name = self.__class__.__name__
        if self.error_code:
            name = f"{name}(code={self.error_code})"
        return name


class PoleEmploiAPIBadResponse(Exception):
    """errors that can't be recovered from: the API server does not agree."""

    def __init__(self, response_code=None, response_data=None):
        self.response_code = response_code
        self.response_data = response_data
        super().__init__()

    def __str__(self):
        name = self.__class__.__name__
        if self.response_code:
            name = f"{name}(code={self.response_code})"
        return name


class IdentityNotCertified(PoleEmploiAPIBadResponse):
    pass


class UserDoesNotExist(PoleEmploiAPIBadResponse):
    pass


class MultipleUsersReturned(PoleEmploiAPIBadResponse):
    pass


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
        self._httpx_client = None

    def __enter__(self):
        self._httpx_client = httpx.Client().__enter__()
        return self

    def __exit__(self, type, value, traceback):
        self._httpx_client.__exit__(type, value, traceback)

    def _get_httpx_client(self):
        return self._httpx_client or httpx.Client()

    def _refresh_token(self):
        scopes = " ".join(self.AUTHORIZED_SCOPES)
        auth_data = (
            self._get_httpx_client()
            .post(
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

            response = self._get_httpx_client().request(
                method=method,
                url=url,
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
            raise PoleEmploiAPIBadResponse(response_code=code_sortie, response_data=data)
        id_national = data.get("idNationalDE")
        if not id_national:
            raise PoleEmploiAPIBadResponse(response_code=API_CLIENT_EMPTY_NIR_BAD_RESPONSE, response_data=data)
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
            raise PoleEmploiAPIBadResponse(response_code=code_sortie, response_data=data)

    def referentiel(self, code):
        return self._request(f"{self.base_url}/offresdemploi/v2/referentiel/{code}", method="GET")

    def offres(self, typeContrat="", natureContrat="", entreprisesAdaptees=None, range=None):
        params = {"typeContrat": typeContrat, "natureContrat": natureContrat}
        if entreprisesAdaptees is not None:
            params["entreprisesAdaptees"] = entreprisesAdaptees
        if range:
            params["range"] = range
        data = self._request(f"{self.base_url}/offresdemploi/v2/offres/search", params=params, method="GET")
        if not data:
            return []
        return data["resultats"]

    def retrieve_all_offres(
        self,
        typeContrat="",
        natureContrat="",
        *,
        entreprisesAdaptees=None,
        delay_between_requests=datetime.timedelta(0),
    ):
        # NOTE: using this unfiltered API we can only sync at most OFFERS_MAX_RANGE offers.
        # If someday there are more offers, we will need to setup a much more complicated sync mechanism, for instance
        # by requesting every department one by one. But so far we are not even close from half this quota.
        raw_offers = []
        for i in range(OFFERS_MIN_INDEX, OFFERS_MAX_INDEX, OFFERS_MAX_RANGE):
            max_range = min(OFFERS_MAX_INDEX, i + OFFERS_MAX_RANGE - 1)
            offers = self.offres(
                typeContrat=typeContrat,
                natureContrat=natureContrat,
                entreprisesAdaptees=entreprisesAdaptees,
                range=f"{i}-{max_range}",
            )
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

    def _request(self, url, data=None, params=None, method="POST", additional_headers=None):
        token = caches["failsafe"].get(self.CACHE_API_TOKEN_KEY)
        if not token:
            token = self._refresh_token()

        # TODO(cms): use real names.
        # These headers MUST be provided.
        # - if not: a 302 will be returned.
        # - if value is an empty string: a 401 will be returned.
        # As of today, no verification seems to be done on FT's side.
        # Any value is good, as far as there is one.
        agents_headers = {
            "pa-nom-agent": "<string>",
            "pa-prenom-agent": "<string>",
            "pa-identifiant-agent": "<string>",
        }
        headers = {"Authorization": token, "Content-Type": "application/json", **agents_headers}
        if additional_headers:
            headers = {**headers, **additional_headers}

        try:
            response = (
                self._get_httpx_client()
                .request(
                    method,
                    url,
                    params=params,
                    json=data,
                    headers=headers,
                    timeout=API_TIMEOUT_SECONDS,
                )
                .raise_for_status()
            )
        except httpx.HTTPStatusError as exc:
            match exc.response.status_code:
                case 429:
                    raise PoleEmploiRateLimitException(error_code=429)
                case 400 | 401 | 403 as error_code:
                    # Should not retry
                    raise PoleEmploiAPIBadResponse(
                        response_code=error_code, response_data=exc.response.json()
                    ) from exc
                case _ as error_code:
                    # Should retry
                    raise PoleEmploiAPIException(error_code=error_code, response_content=exc.response.content) from exc

        return response.json()

    def _rechercher_usager_by_pole_emploi_id(self, pole_emploi_id):
        if not pole_emploi_id:
            raise TypeError("`pole_emploi_id` is mandatory.")
        return self._request(
            f"{self.base_url}/rechercher-usager/v2/usagers/par-numero-francetravail",
            {
                "numeroFranceTravail": pole_emploi_id,
            },
        )

    def _rechercher_usager_by_birthdate_and_nir(self, birthdate, nir):
        if not (birthdate and nir):
            raise TypeError("`birthdate` and `nir` are mandatory.")
        return self._request(
            f"{self.base_url}/rechercher-usager/v2/usagers/par-datenaissance-et-nir",
            {
                "dateNaissance": birthdate.strftime(DATE_FORMAT),
                "nir": nir,
            },
        )

    def rechercher_usager(self, jobseeker_profile):
        """Find a user by pivot data (birthdate and nir or pole_emploi_id)
        and return a crypted token (`jeton usager`).
        `profile`: users.models.JobSeekerProfile (not included as a type hint because of a circular import issue).
        return: "a_long_jeton_usager"
        """
        birthdate, nir, pole_emploi_id = (
            jobseeker_profile.birthdate,
            jobseeker_profile.nir,
            jobseeker_profile.pole_emploi_id,
        )
        if birthdate and nir:
            data = self._rechercher_usager_by_birthdate_and_nir(birthdate=birthdate, nir=nir)
        elif pole_emploi_id:
            data = self._rechercher_usager_by_pole_emploi_id(pole_emploi_id=pole_emploi_id)
        else:
            raise TypeError("Please provide a birthdate and a nir or a pole_emploi_id.")

        match data["codeRetour"]:
            case "S001":
                pass
            case "S002":
                raise UserDoesNotExist()
            case "S003":
                raise MultipleUsersReturned()
            case _ as response_code:
                raise PoleEmploiAPIBadResponse(response_code=response_code, response_data=data)

        if data["topIdentiteCertifiee"] != "O":
            raise IdentityNotCertified()

        return data["jetonUsager"]

    def certify_rqth(self, jobseeker_profile):
        jeton_usager = self.rechercher_usager(jobseeker_profile=jobseeker_profile)
        data = self._request(
            f"{self.base_url}/donnees-rqth/v1/rqth", method="GET", additional_headers={"ft-jeton-usager": jeton_usager}
        )
        certified = data["topValiditeRQTH"] is True
        end_at = data["dateFinRqth"] if certified else None
        if end_at:
            end_at = datetime.date.fromisoformat(data["dateFinRqth"])
            if end_at == datetime.date(9999, 12, 31):
                end_at = None
        return {
            "is_certified": certified,
            "start_at": datetime.date.fromisoformat(data["dateDebutRqth"]) if certified else None,
            "end_at": end_at,
            "raw_response": data,
        }


def pole_emploi_partenaire_api_client():
    return PoleEmploiRoyaumePartenaireApiClient(
        settings.API_ESD["BASE_URL"],
        settings.API_ESD["AUTH_BASE_URL"],
        settings.API_ESD["KEY"],
        settings.API_ESD["SECRET"],
    )


def pole_emploi_agent_api_client():
    return PoleEmploiRoyaumeAgentAPIClient(
        settings.API_ESD["BASE_URL"],
        settings.API_ESD["AUTH_BASE_URL"],
        settings.API_ESD["KEY"],
        settings.API_ESD["SECRET"],
    )
