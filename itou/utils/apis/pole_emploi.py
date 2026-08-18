"""This is a client for api.francetravail.io

It needs a few environment variables to work, see `git grep API_ESD`.

For example, to access partner API, one can use:

export API_ESD_AUTH_BASE_URL_PARTENAIRE='https://entreprise.francetravail.fr'
export API_ESD_BASE_URL='https://api.francetravail.io/partenaire'
export API_ESD_KEY="$(pass inclusion/api-france-travail-key)"
export API_ESD_SECRET="$(pass inclusion/api-france-travail-secret)"
"""

import datetime
import enum
import json
import logging
import re
import time
from typing import TYPE_CHECKING

import httpx
from django.conf import settings
from django.core.cache import caches
from unidecode import unidecode

from itou.utils.types import InclusiveDateRange


if TYPE_CHECKING:
    from itou.users.models import JobSeekerProfile


logger = logging.getLogger(__name__)

API_CLIENT_HTTP_ERROR_CODE = "http_error"
REFRESH_TOKEN_MARGIN_SECONDS = 10  # arbitrary value, in order not to be *right* on the expiry time.


class Apps(enum.Enum):
    EMPLOIS = "emplois"
    SPS = "sps"


class Endpoints(enum.StrEnum):
    DIAGNOSTIC_USAGER_DIAGNOSTIC_AGREGE = "/diagnosticargumente/v4/dossiers"
    INFORMATIONS_ADMINISTRATIVES_USAGER = "/informations-administratives/v1/usager"
    LECTURE_ORIENTATION_USAGER = "/orientationusager/v1/lectureOrientation"
    RECHERCHER_USAGER_DATE_NAISSANCE_NIR = "/rechercher-usager/v2/usagers/par-datenaissance-et-nir"
    RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL = "/rechercher-usager/v2/usagers/par-numero-francetravail"
    RQTH = "/donnees-rqth/v1/rqth"
    STATUT_USAGER = "/contrat-usager/v2/contrat"


class TopIdentiteCertifiee(enum.StrEnum):
    YES = "O"
    NO = "N"
    NA = "null"


# Source:
# https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation#/api-reference/operations/recupererListeOffre
OFFERS_MIN_INDEX = 0
OFFERS_MAX_INDEX = 3149
OFFERS_MAX_RANGE = 150


def get_credentials(app):
    # We use a match/case instead of {...}[app] so that we don't need all keys to be there
    # It will make overriding the settings easier in tests
    match app:
        case Apps.EMPLOIS:
            return {
                "key": settings.API_ESD["KEY"],
                "secret": settings.API_ESD["SECRET"],
            }
        case Apps.SPS:
            return {
                "key": settings.API_ESD["RECOMMENDATIONS_KEY"],
                "secret": settings.API_ESD["RECOMMENDATIONS_SECRET"],
            }
    raise ValueError(f"Unknown app: {app}")


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
    def __init__(self, error_code=None, response_content=None, retry_after=0):
        super().__init__(error_code, response_content)
        self.retry_after = retry_after


API_CLIENT_EMPTY_NIR_BAD_RESPONSE = "empty_nir"


API_TIMEOUT_SECONDS = 60  # this API is pretty slow, let's give it a chance

API_MAJ_PASS_SUCCESS = "S000"
API_RECH_INDIVIDU_SUCCESS = "S001"
DATE_FORMAT = "%Y-%m-%d"
MAX_NIR_CHARACTERS = 13  # France Travail only cares about the first 13 characters of the NIR.


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
    REALM = ""

    def __init__(self, base_url, auth_base_url, key, secret) -> None:
        if not self.REALM:
            raise NotImplementedError("Realm missing.")
        self.needed_scopes: set[str] = set()
        self.base_url = base_url
        self.auth_base_url = auth_base_url
        self.key = key
        self.secret = secret
        self._httpx_client = None

    @property
    def cache_api_token_key(self) -> str:
        """Generate a cache key for an API token.

        If the scopes have changed (more are needed compared to the
        current token) the cache key change, so a new key is generated
        for a token having the new scopes.
        """
        return type(self).__name__ + self.scopes

    @property
    def scopes(self) -> str:
        """From the set of needed scopes, reteurn a string of all scopes.

        Useful to generate a token and a token cache key.

        It has to be stable (sorted in the current case) as it is used
        as a cache key.
        """
        return " ".join(sorted(self.needed_scopes))

    def __enter__(self):
        self._httpx_client = httpx.Client().__enter__()
        return self

    def __exit__(self, type, value, traceback):
        self._httpx_client.__exit__(type, value, traceback)

    def _get_httpx_client(self):
        return self._httpx_client or httpx.Client()

    def _refresh_token(self):
        auth_data = (
            self._get_httpx_client()
            .post(
                f"{self.auth_base_url}/connexion/oauth2/access_token",
                params={"realm": self.REALM},
                data={
                    "client_id": self.key,
                    "client_secret": self.secret,
                    "grant_type": "client_credentials",
                    "scope": f"application_{self.key} {self.scopes}",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            .raise_for_status()
            .json()
        )
        token = f"{auth_data['token_type']} {auth_data['access_token']}"
        caches["failsafe"].set(
            self.cache_api_token_key,
            token,
            auth_data["expires_in"]
            - REFRESH_TOKEN_MARGIN_SECONDS,  # make the token expire a little sooner than expected
        )
        return token

    def _header(self, token, **kwargs):
        return {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    def _request(self, url, data=None, params=None, method="POST", **kwargs):
        try:
            token = caches["failsafe"].get(self.cache_api_token_key)
            if not token:
                token = self._refresh_token()

            response = self._get_httpx_client().request(
                method=method,
                url=url,
                params=params,
                json=data,
                headers=self._header(token, **kwargs),
                timeout=API_TIMEOUT_SECONDS,
            )

            if response.status_code == 204:
                return None
            if response.status_code == 429:
                logger.warning("Request on url=%s triggered rate limit", url)
                # https://francetravail.io/produits-partages/documentation/utilisation-api-france-travail/erreurs-frequentes#:~:text=429 Too Many Requests  # noqa: E501
                raise PoleEmploiRateLimitException(429, retry_after=response.headers.get("Retry-After", "60"))
            if response.status_code not in (200, 206):
                logger.warning("Request on url=%s returned status_code=%s", url, response.status_code)
                try:
                    content = response.json()
                    # This might look like:
                    # {'codeErreur': 'JCS0011G', 'codeHttp': 500,
                    #  'message': 'La vue service retournée par le connecteur HTTP est nulle ou mal formée'}
                except json.decoder.JSONDecodeError:
                    content = response.content
                raise PoleEmploiAPIException(error_code=response.status_code, response_content=content)
            data = response.json()
            return data
        except httpx.RequestError as exc:
            raise PoleEmploiAPIException(API_CLIENT_HTTP_ERROR_CODE) from exc


class PoleEmploiRoyaumePartenaireApiClient(BasePoleEmploiApiClient):
    # France Travail also sent us a "sandbox" scope value: "api_testmaj-pass-iaev1" instead of "api_maj-pass-iaev1"
    REALM = "/partenaire"

    def recherche_individu_certifie(self, first_name, last_name, birthdate, nir):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/recherche-individu-certifie/documentation
        (This documentation needs you to be logged-in.)

        Example data:
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
        self.needed_scopes |= {"api_rechercheindividucertifiev1", "rechercherIndividuCertifie"}
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
        """
        API documentation:
        https://francetravail.io/produits-partages/catalogue/mise-jour-passiae/documentation#/api-reference/operations/miseAjourPassIAE

        Example of a JSON response:

            {'codeSortie': 'S000', 'idNational': 'some identifier', 'message': 'Pass IAE prescrit'}

        The only valid result is HTTP 200 + codeSortie = "S000".
        Anything else (other HTTP code, or different codeSortie) means that our notification has been discarded.
        """
        self.needed_scopes |= {"passIAE", "api_maj-pass-iaev1"}
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

    def referentiel(self, code, cache_timeout=datetime.timedelta(days=7).total_seconds()):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation
        """
        cache_key = f"{str(type(self))}.referentiel({code})"
        result = caches["failsafe"].get(cache_key)
        if result:
            return result
        self.needed_scopes |= {"o2dsoffre", "api_offresdemploiv2"}
        result = self._request(f"{self.base_url}/offresdemploi/v2/referentiel/{code}", method="GET")
        caches["failsafe"].set(cache_key, result, cache_timeout)
        return result

    def offres(
        self,
        typeContrat="",
        natureContrat="",
        entreprisesAdaptees=None,
        employeursHandiEngages=None,
        departement=None,
        range=None,
    ):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation

        Attention aux paramètres :

        - Entre entreprisesAdaptees et employeursHandiEngages c'est un
          « OU », probablement parce que c'est dans la même catégorie
          « handicap » sur le site de france travail.

        - natureContrat implique un « ET » avec les paramètres des
          autres catégories (dont la catégorie handicap).

        Par exemple, en 2026 :
        - On a 61 offres contrat PEC
        - On a 7964 offres d'employeurs handi engagés
        - On a 655 offres d'entreprises adaptées
        - Si on requête employeursHandiEngages=True, entreprisesAdaptees=True on a 8004 offres
        - Si on requête natureContrat=pe_api_enums.NATURE_CONTRAT_PEC,
          employeursHandiEngages=True, entreprisesAdaptees=True on a seulement 2 offres.
        """
        self.needed_scopes |= {"o2dsoffre", "api_offresdemploiv2"}
        params = {"typeContrat": typeContrat, "natureContrat": natureContrat}
        if entreprisesAdaptees is not None:
            params["entreprisesAdaptees"] = entreprisesAdaptees
        if employeursHandiEngages is not None:
            params["employeursHandiEngages"] = employeursHandiEngages
        if departement is not None:
            params["departement"] = departement
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
        employeursHandiEngages=None,
        delay_between_requests=datetime.timedelta(0),
    ):
        """We split requests by departments to break the API limit at 3149.

        It is needed because FT have, as of 2026, around 8k offers
        from Employeurs Handi Engagés.

        See this page to get counts from FT:

        https://candidat.francetravail.fr/offres/recherche?lieux=99100&offresPartenaires=true&rayon=10&tri=0

        Don't forget to simplify that code if France Travail removes
        the restriction of 3149 paginated results, which is documented
        in the `range` section of:

        https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation#/api-reference/operations/recupererListeOffre
        """

        raw_offers = []
        for departement in self.referentiel("departements"):
            for range_start in range(OFFERS_MIN_INDEX, OFFERS_MAX_INDEX, OFFERS_MAX_RANGE):
                range_stop = range_start + OFFERS_MAX_RANGE - 1
                offers = self.offres(
                    typeContrat=typeContrat,
                    natureContrat=natureContrat,
                    entreprisesAdaptees=entreprisesAdaptees,
                    employeursHandiEngages=employeursHandiEngages,
                    departement=departement["code"],
                    range=f"{range_start}-{range_stop}",
                )
                logger.info(f"retrieved count={len(offers)} offers from FT API")
                time.sleep(delay_between_requests.total_seconds())
                raw_offers.extend(offers)
                if len(offers) < OFFERS_MAX_RANGE:
                    break
                if range_stop == OFFERS_MAX_INDEX and len(offers) == OFFERS_MAX_RANGE:
                    logger.error("FT API returned the maximum number of offers: some offers are likely missing")
        return raw_offers

    def appellations(self):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/rome-4-0-metiers/documentation
        """
        self.needed_scopes |= {"nomenclatureRome", "api_rome-metiersv1"}
        return self._request(
            f"{self.base_url}/rome-metiers/v1/metiers/appellation?champs=code,libelle,metier(code)",
            method="GET",
        )

    def agences(self, safir=None):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/referentiel-agences/documentation
        """
        self.needed_scopes |= {"api_referentielagencesv1", "organisationpe"}
        agences = self._request(f"{self.base_url}/referentielagences/v1/agences", method="GET")
        if safir:
            return next((agence for agence in agences if agence["codeSafir"] == str(safir)), None)
        return agences


class PoleEmploiRoyaumeAgentAPIClient(BasePoleEmploiApiClient):
    REALM = "/agent"

    def _header(self, token, jeton_usager=None):
        headers = {
            "Authorization": token,
            "Content-Type": "application/json",
            # It’s not obvious what values to pass for the following headers.
            # The requester can be an employer, a prescriber from an
            # organization that’s not FT.
            # These headers MUST be provided.
            # - if not: a 302 will be returned.
            # - if value is an empty string: a 401 will be returned.
            # As of today, no verification seems to be done on FT's side.
            # Any value is good, use these placeholders.
            "pa-nom-agent": "<string>",
            "pa-prenom-agent": "<string>",
            "pa-identifiant-agent": "<string>",
        }
        if jeton_usager is not None:
            headers["ft-jeton-usager"] = jeton_usager
        return headers

    def _rechercher_usager_by_pole_emploi_id(self, pole_emploi_id):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/rechercher-usager/documentation
        """
        if not pole_emploi_id:
            raise TypeError("`pole_emploi_id` is mandatory.")
        self.needed_scopes |= {"api_rechercher-usagerv2", "profil_accedant", "rechercheusager"}
        return self._request(
            f"{self.base_url}{Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL}",
            {
                "numeroFranceTravail": pole_emploi_id,
            },
        )

    def _rechercher_usager_by_birthdate_and_nir(self, birthdate, nir):
        """API documentation:
        https://francetravail.io/produits-partages/catalogue/rechercher-usager/documentation
        """
        if not (birthdate and nir):
            raise TypeError("`birthdate` and `nir` are mandatory.")
        self.needed_scopes |= {"api_rechercher-usagerv2", "profil_accedant", "rechercheusager"}
        return self._request(
            f"{self.base_url}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}",
            {
                "dateNaissance": birthdate.strftime(DATE_FORMAT),
                "nir": nir,
            },
        )

    def rechercher_usager(
        self, jobseeker_profile: "JobSeekerProfile | None" = None, france_travail_id: str | None = None
    ):
        """Find a user by pivot data (birthdate and nir or pole_emploi_id)
        and return a crypted token (`jeton usager`).
        """
        assert (jobseeker_profile is None) ^ (france_travail_id is None), (
            "One and only one of jobseeker_profile and france_travail_id is required"
        )
        if jobseeker_profile:
            birthdate, nir, pole_emploi_id = (
                jobseeker_profile.birthdate,
                jobseeker_profile.nir,
                jobseeker_profile.pole_emploi_id,
            )
        else:
            birthdate = nir = None
            pole_emploi_id = france_travail_id
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
                raise UserDoesNotExist(response_data=data)
            case "S003":
                raise MultipleUsersReturned(response_data=data)
            case _ as response_code:
                raise PoleEmploiAPIBadResponse(response_code=response_code, response_data=data)

        if data["topIdentiteCertifiee"] != TopIdentiteCertifiee.YES:
            raise IdentityNotCertified(response_data=data)

        return data["jetonUsager"]

    def rqth(self, jeton_usager):
        data = self._request(
            f"{self.base_url}{Endpoints.RQTH}",
            method="GET",
            jeton_usager=jeton_usager,
        )
        if data["topValiditeRQTH"]:
            start_at = datetime.date.fromisoformat(data["dateDebutRqth"])
            end_at = data["dateFinRqth"]
            if end_at is not None:
                end_at = datetime.date.fromisoformat(end_at)
                if end_at == datetime.date(9999, 12, 31):
                    end_at = None
            certification_period = InclusiveDateRange(start_at, end_at)
        else:
            certification_period = InclusiveDateRange(empty=True)
        return {
            "certification_period": certification_period,
            "raw_response": data,
        }

    def informations_administratives_usager(self, jeton_usager):
        # https://francetravail.io/produits-partages/catalogue/rechercher-usager/informations-administratives-usager/documentation#/api-reference/operations/recupererDonneesParIdRci
        return self._request(
            f"{self.base_url}{Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER}",
            method="GET",
            jeton_usager=jeton_usager,
        )

    def statut_usager(self, jeton_usager):
        # https://francetravail.io/produits-partages/catalogue/rechercher-usager/statut-usager/documentation#/api-reference/operations/recupererContratV2
        return self._request(
            f"{self.base_url}{Endpoints.STATUT_USAGER}",
            method="GET",
            jeton_usager=jeton_usager,
        )

    def orientation_usager(self, jeton_usager):
        # https://francetravail.io/produits-partages/catalogue/rechercher-usager/orientation-usager/documentation#/api-reference/paths/lectureOrientation/get
        return self._request(
            f"{self.base_url}{Endpoints.LECTURE_ORIENTATION_USAGER}",
            method="GET",
            params={"etatOrientation": "OUVERT"},
            jeton_usager=jeton_usager,
        )

    def diagnostic_usager_dossier_agrege(self, jeton_usager):
        # https://francetravail.io/produits-partages/catalogue/rechercher-usager/diagnostics-individus/documentation#/api-reference/operations/recupererDossierIndividuV4
        return self._request(
            f"{self.base_url}{Endpoints.DIAGNOSTIC_USAGER_DIAGNOSTIC_AGREGE}",
            method="GET",
            jeton_usager=jeton_usager,
        )


def pole_emploi_partenaire_api_client(app=Apps.EMPLOIS):
    return PoleEmploiRoyaumePartenaireApiClient(
        settings.API_ESD["BASE_URL"],
        settings.API_ESD["AUTH_BASE_URL_PARTENAIRE"],
        **get_credentials(app),
    )


def pole_emploi_agent_api_client(app=Apps.EMPLOIS):
    return PoleEmploiRoyaumeAgentAPIClient(
        settings.API_ESD["BASE_URL"],
        settings.API_ESD["AUTH_BASE_URL_AGENT"],
        **get_credentials(app),
    )
