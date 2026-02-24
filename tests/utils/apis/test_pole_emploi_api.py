import datetime
import json
import math
import time

import httpx
import pytest
import respx
from django.conf import settings
from django.core.cache import caches
from django_redis import get_redis_connection

from itou.utils.apis.enums import PEApiRechercheIndividuExitCode
from itou.utils.apis.pole_emploi import (
    REFRESH_TOKEN_MARGIN_SECONDS,
    Endpoints,
    IdentityNotCertified,
    MultipleUsersReturned,
    PoleEmploiAPIBadResponse,
    PoleEmploiAPIException,
    PoleEmploiRateLimitException,
    PoleEmploiRoyaumeAgentAPIClient,
    PoleEmploiRoyaumePartenaireApiClient,
    UserDoesNotExist,
    pole_emploi_agent_api_client,
)
from itou.utils.mocks.pole_emploi import (
    API_APPELLATIONS_RESPONSE_OK,
    API_MAJPASS_RESPONSE_ERROR,
    API_MAJPASS_RESPONSE_OK,
    API_OFFRES_RESPONSE_OK,
    API_RECHERCHE_RESPONSE_ERROR,
    API_RECHERCHE_RESPONSE_KNOWN,
    API_REFERENTIEL_NATURE_CONTRATS_RESPONSE_OK,
    RESPONSES,
    ResponseKind,
)
from itou.utils.types import InclusiveDateRange
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory, JobSeekerProfileFactory


class TestPoleEmploiRoyaumePartenaireApiClient:
    CACHE_EXPIRY = 3600

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.api_client = PoleEmploiRoyaumePartenaireApiClient(
            "https://pe.fake", "https://auth.fr", "foobar", "pe-secret"
        )
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": self.CACHE_EXPIRY}
        )

    @respx.mock
    def test_get_token_nominal(self):
        start = math.floor(time.time())  # Ignore microseconds.
        self.api_client._refresh_token()
        cache = caches["failsafe"]
        assert cache.get(PoleEmploiRoyaumePartenaireApiClient.CACHE_API_TOKEN_KEY) == "foo batman"
        redis_client = get_redis_connection("failsafe")
        expiry = redis_client.expiretime(cache.make_key(PoleEmploiRoyaumePartenaireApiClient.CACHE_API_TOKEN_KEY))
        assert start + self.CACHE_EXPIRY - REFRESH_TOKEN_MARGIN_SECONDS <= expiry <= start + self.CACHE_EXPIRY

    @respx.mock
    def test_get_token_fails(self):
        job_seeker = JobSeekerFactory()
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").mock(
            side_effect=httpx.ConnectTimeout
        )
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name,
                job_seeker.last_name,
                job_seeker.jobseeker_profile.birthdate,
                job_seeker.jobseeker_profile.nir,
            )
        assert ctx.value.error_code == "http_error"

    @respx.mock
    def test_httpx_client(self):
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": self.CACHE_EXPIRY}
        )
        respx.get("https://pe.fake/rome-metiers/v1/metiers/appellation?champs=code,libelle,metier(code)").respond(
            200,
            json=API_APPELLATIONS_RESPONSE_OK,
        )
        respx.get("https://pe.fake/offresdemploi/v2/referentiel/naturesContrats").respond(
            200, json=API_REFERENTIEL_NATURE_CONTRATS_RESPONSE_OK
        )

        # Connection pooling
        client = PoleEmploiRoyaumePartenaireApiClient("https://pe.fake", "https://auth.fr", "foobar", "pe-secret")
        with client:
            first_client = client._get_httpx_client()
            assert client._refresh_token() == "foo batman"
            assert client.appellations() == API_APPELLATIONS_RESPONSE_OK
            assert client.referentiel("naturesContrats") == API_REFERENTIEL_NATURE_CONTRATS_RESPONSE_OK
            assert first_client is client._get_httpx_client()

        # Outside a context manager…
        # …an error is raised if we try to reuse a client previously created by a context manager…
        with pytest.raises(RuntimeError, match="Cannot send a request, as the client has been closed"):
            client.appellations()

        # …but if no context manager was used before, a new HTTPX client is created for each new request.
        client = PoleEmploiRoyaumePartenaireApiClient("https://pe.fake", "https://auth.fr", "foobar", "pe-secret")
        assert client._refresh_token() == "foo batman"
        first_client = client._get_httpx_client()
        assert client.appellations() == API_APPELLATIONS_RESPONSE_OK
        assert first_client is not client._get_httpx_client()

    @respx.mock
    def test_recherche_individu_certifie_api_nominal(self):
        job_seeker = JobSeekerFactory()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESPONSE_KNOWN
        )
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name,
            job_seeker.last_name,
            job_seeker.jobseeker_profile.birthdate,
            job_seeker.jobseeker_profile.nir,
        )
        assert id_national == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"

        # now with weird payloads
        job_seeker.first_name = "marié%{-christine}  aéïèêë " + "a" * 50
        job_seeker.last_name = "gh'îkñ Bind-n'qici " + "b" * 50
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name,
            job_seeker.last_name,
            job_seeker.jobseeker_profile.birthdate,
            job_seeker.jobseeker_profile.nir,
        )
        payload = json.loads(respx.calls.last.request.content)
        assert payload["nomNaissance"] == "GH'IKN BIND-N'QICI BBBBBB"  # 25 chars
        assert payload["prenom"] == "MARIE-CHRISTI"  # 13 chars

    @respx.mock
    def test_recherche_individu_certifie_individual_api_errors(self):
        job_seeker = JobSeekerFactory()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESPONSE_ERROR
        )
        with pytest.raises(PoleEmploiAPIBadResponse) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name,
                job_seeker.last_name,
                job_seeker.jobseeker_profile.birthdate,
                job_seeker.jobseeker_profile.nir,
            )
        assert ctx.value.response_code == PEApiRechercheIndividuExitCode.R010
        assert ctx.value.response_data == API_RECHERCHE_RESPONSE_ERROR

    @respx.mock
    def test_recherche_individu_certifie_retryable_errors(self):
        job_seeker = JobSeekerFactory()

        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(401, json="")
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name,
                job_seeker.last_name,
                job_seeker.jobseeker_profile.birthdate,
                job_seeker.jobseeker_profile.nir,
            )
        assert ctx.value.error_code == 401

        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(429, json="")
        with pytest.raises(PoleEmploiRateLimitException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name,
                job_seeker.last_name,
                job_seeker.jobseeker_profile.birthdate,
                job_seeker.jobseeker_profile.nir,
            )

        job_seeker = JobSeekerFactory()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").mock(
            side_effect=httpx.ConnectTimeout
        )
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name,
                job_seeker.last_name,
                job_seeker.jobseeker_profile.birthdate,
                job_seeker.jobseeker_profile.nir,
            )
        assert ctx.value.error_code == "http_error"

    @respx.mock
    def test_mise_a_jour_pass_iae_success_with_approval_accepted(self):
        """
        Nominal scenario: an approval is **accepted**
        HTTP 200 + codeSortie = S001 is the only way mise_a_jour_pass_iae does not raise.
        """
        job_application = JobApplicationFactory(with_approval=True)
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESPONSE_OK)
        # we really don't care about the arguments there
        self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

    @respx.mock
    def test_mise_a_jour_pass_iae_failure(self):
        job_application = JobApplicationFactory(with_approval=True)
        # non-S001 codeSortie
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESPONSE_ERROR)
        with pytest.raises(PoleEmploiAPIBadResponse):
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

        # timeout
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").mock(side_effect=httpx.ConnectTimeout)
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")
        assert ctx.value.error_code == "http_error"

        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(429, json={})
        with pytest.raises(PoleEmploiRateLimitException):
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

        # auth failed
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(401, json={})
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")
        assert ctx.value.error_code == 401

    @respx.mock
    def test_referentiel(self):
        respx.get("https://pe.fake/offresdemploi/v2/referentiel/naturesContrats").respond(
            200, json=API_REFERENTIEL_NATURE_CONTRATS_RESPONSE_OK
        )
        assert self.api_client.referentiel("naturesContrats") == API_REFERENTIEL_NATURE_CONTRATS_RESPONSE_OK

    @respx.mock
    def test_offres(self):
        respx.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT&range=0-1").respond(
            206,  # test code 206 as we already know that 200 is tested through the other tests
            json={"resultats": API_OFFRES_RESPONSE_OK},
        )
        assert self.api_client.offres(natureContrat="FT", range="0-1") == API_OFFRES_RESPONSE_OK
        respx.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=&range=100-140").respond(
            204
        )
        assert self.api_client.offres(range="100-140") == []

        EA_OFFERS = [{**offer, "entrepriseAdaptee": True} for offer in API_OFFRES_RESPONSE_OK]

        respx.get(
            "https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=&entreprisesAdaptees=true&range=0-1"
        ).respond(
            206,  # test code 206 as we already know that 200 is tested through the other tests
            json={"resultats": EA_OFFERS},
        )
        assert self.api_client.offres(entreprisesAdaptees=True, range="0-1") == EA_OFFERS

    @respx.mock
    def test_appellations(self):
        respx.get("https://pe.fake/rome-metiers/v1/metiers/appellation?champs=code,libelle,metier(code)").respond(
            200,
            json=API_APPELLATIONS_RESPONSE_OK,
        )
        assert self.api_client.appellations() == API_APPELLATIONS_RESPONSE_OK

    @respx.mock
    def test_agences(self):
        expected_agence = {
            "code": "OCC0043",
            "codeSafir": "82001",
            "libelle": "MONTAUBAN ALBASUD",
            "libelleEtendu": "Agence France Travail MONTAUBAN ALBASUD",
            "type": "APE",
            "typeAccueil": "3",
            "codeRegionINSEE": "76",
            "dispositifADEDA": True,
            "contact": {"telephonePublic": "39-49", "email": "ape.82001@francetravail.fr"},
            "adressePrincipale": {
                "ligne3": "Zone d'activités Albasud",
                "ligne4": "205 AV de l'Europe",
                "ligne5": "",
                "ligne6": "82000 MONTAUBAN",
                "gpsLon": 1.33531,
                "gpsLat": 43.996864,
                "communeImplantation": "82121",
                "bureauDistributeur": "82000",
            },
            "siret": "13000548121305",
        }
        other_agence = {
            "code": "NAQ0146",
            "codeSafir": "33041",
            "libelle": "LIBOURNE",
            "libelleEtendu": "Agence France Travail LIBOURNE",
            "type": "APE",
            "typeAccueil": "3",
            "codeRegionINSEE": "75",
            "dispositifADEDA": True,
            "contact": {"telephonePublic": "39-49", "email": "ape.33041@francetravail.fr"},
            "adressePrincipale": {
                "ligne4": "33 CHEMIN DU CASSE",
                "ligne5": "",
                "ligne6": "33500 LIBOURNE",
                "gpsLon": -0.22241,
                "gpsLat": 44.918006,
                "communeImplantation": "33243",
                "bureauDistributeur": "33500",
            },
            "siret": "13000548122147",
        }

        respx.get("https://pe.fake/referentielagences/v1/agences").respond(
            200,
            json=[expected_agence, other_agence],
        )
        assert self.api_client.agences() == [expected_agence, other_agence]
        assert self.api_client.agences(safir=82001) == expected_agence


class TestPoleEmploiRoyaumeAgentAPIClient:
    CACHE_EXPIRY = 1499

    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.API_ESD = {
            "BASE_URL": "https://pe.fake",
            "AUTH_BASE_URL_AGENT": "https://auth.fr",
            "KEY": "foobar",
            "SECRET": "pe-secret",
        }
        self.api_client = pole_emploi_agent_api_client()
        json_response = {
            "token_type": "Bearer",
            "access_token": "Catwoman",
            "scope": "client_id h2a rechercheusager profil_accedant api_donnees-rqthv1 api_rechercher-usagerv2",
            "expires_in": self.CACHE_EXPIRY,
        }
        respx.post(f"{settings.API_ESD['AUTH_BASE_URL_AGENT']}/connexion/oauth2/access_token?realm=%2Fagent").respond(
            200, json=json_response
        )

    @respx.mock
    def test_refresh_token(self):
        # This method is already tested on TestPoleEmploiRoyaumePartenaireApiClient.
        token = self.api_client._refresh_token()
        assert token == "Bearer Catwoman"

    @respx.mock
    def test_request_caches_token(self):
        rechercher_usager_url = f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}"
        respx.post(rechercher_usager_url).respond(200, json={"sample": "data"})
        self.api_client._request(rechercher_usager_url)
        assert caches["failsafe"].get(PoleEmploiRoyaumeAgentAPIClient.CACHE_API_TOKEN_KEY) == "Bearer Catwoman"

    @respx.mock
    def test_request_http_request_headers(self):
        rechercher_usager_url = f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}"
        mock = respx.post(rechercher_usager_url).respond(200, json={"sample": "data"})
        self.api_client._request(rechercher_usager_url)
        expected_headers = {
            "Authorization": "Bearer Catwoman",
            "Content-Type": "application/json",
            "pa-nom-agent": "<string>",
            "pa-prenom-agent": "<string>",
            "pa-identifiant-agent": "<string>",
        }
        headers = mock.calls[-1].request.headers
        for key, value in expected_headers.items():
            assert headers[key] == value

    @respx.mock
    def test_request_http_jeton_usager(self):
        rechercher_usager_url = f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}"
        mock = respx.post(rechercher_usager_url).respond(200, json={"sample": "data"})
        self.api_client._request(rechercher_usager_url, jeton_usager="something-very-long")
        expected_headers = {
            "Authorization": "Bearer Catwoman",
            "Content-Type": "application/json",
            "pa-nom-agent": "<string>",
            "pa-prenom-agent": "<string>",
            "pa-identifiant-agent": "<string>",
            "ft-jeton-usager": "something-very-long",
        }
        headers = mock.calls[-1].request.headers
        for key, value in expected_headers.items():
            assert headers[key] == value

    @respx.mock
    def test_rechercher_usager_by_birthdate_and_nir(self):
        respx.post(f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}").respond(
            200, json=RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.CERTIFIED]
        )
        jeton_usager = self.api_client.rechercher_usager(jobseeker_profile=JobSeekerProfileFactory())
        assert jeton_usager == "a_long_token"

    @respx.mock
    def test_rechercher_usager_by_pole_emploi_id(self):
        respx.post(f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL}").respond(
            200, json=RESPONSES[Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL][ResponseKind.CERTIFIED]
        )
        jobseeker_profile = JobSeekerProfileFactory(birthdate=None, nir="", pole_emploi_id="12345678901")
        jeton_usager = self.api_client.rechercher_usager(jobseeker_profile=jobseeker_profile)
        assert jeton_usager == "a_long_token"

    @pytest.mark.parametrize(
        "json_response,exception_raised,exception_pattern",
        [
            pytest.param(
                RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.NOT_FOUND],
                UserDoesNotExist,
                r"UserDoesNotExist",
                id="user_does_not_exist",
            ),
            pytest.param(
                RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.NOT_CERTIFIED],
                IdentityNotCertified,
                r"IdentityNotCertified",
                id="identity_not_certified",
            ),
            pytest.param(
                RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.MULTIPLE_USERS_RETURNED],
                MultipleUsersReturned,
                r"MultipleUsersReturned",
                id="multiple_users_returned",
            ),
            pytest.param(
                {
                    "codeRetour": "S009",
                    "message": "Nouveau cas non identifié",
                    "jetonUsager": None,
                    "topIdentiteCertifiee": None,
                },
                PoleEmploiAPIBadResponse,
                r"PoleEmploiAPIBadResponse\(code=S009\)",
                id="unknown_successful_response_code",
            ),
        ],
    )
    @respx.mock
    def test_rechercher_usager_response_exceptions(self, json_response, exception_raised, exception_pattern):
        url = f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}"
        respx.post(url).respond(200, json=json_response)
        with pytest.raises(exception_raised, match=exception_pattern):
            self.api_client.rechercher_usager(jobseeker_profile=JobSeekerProfileFactory())

    @respx.mock
    def test_rechercher_usager_calls_nir_endpoint(self):
        json_response = RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.CERTIFIED]
        mock_birthdate_nir = respx.post(
            f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR}"
        ).respond(200, json=json_response)
        mock_pole_emploi_id = respx.post(
            f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL}"
        ).respond(200, json=json_response)

        token = self.api_client.rechercher_usager(jobseeker_profile=JobSeekerProfileFactory())
        assert token == "a_long_token"
        assert mock_birthdate_nir.called
        assert not mock_pole_emploi_id.called

    @respx.mock
    def test_rechercher_usager_calls_pole_emploi_id_endpoint(self):
        json_response = RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.CERTIFIED]
        mock_birthdate_nir = respx.post(
            settings.API_ESD["BASE_URL"] + Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        ).respond(200, json=json_response)
        mock_pole_emploi_id = respx.post(
            settings.API_ESD["BASE_URL"] + Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL
        ).respond(200, json=json_response)

        jobseeker_profile = JobSeekerProfileFactory(birthdate=None, nir="", pole_emploi_id="12345678910")
        token = self.api_client.rechercher_usager(jobseeker_profile=jobseeker_profile)
        assert token == "a_long_token"
        assert not mock_birthdate_nir.called
        assert mock_pole_emploi_id.called

    @pytest.mark.parametrize(
        "json_response,expected_data",
        [
            pytest.param(
                RESPONSES[Endpoints.RQTH][ResponseKind.CERTIFIED],
                {"certification_period": InclusiveDateRange(datetime.date(2024, 1, 20), datetime.date(2030, 1, 20))},
                id="certified",
            ),
            pytest.param(
                RESPONSES[Endpoints.RQTH][ResponseKind.NOT_CERTIFIED],
                {"certification_period": InclusiveDateRange(empty=True)},
                id="not_certified",
            ),
            pytest.param(
                RESPONSES[Endpoints.RQTH][ResponseKind.CERTIFIED_FOR_EVER],
                {"certification_period": InclusiveDateRange(datetime.date(2024, 1, 20))},
                id="certified_for_ever",
            ),
            # As for now, the API returns `"dateFinRqth": "9999-12-31"`
            # if the RQTH has no end but this may change one day.
            # Be future-proof by testing this possible case.
            pytest.param(
                {
                    "dateDebutRqth": "2024-01-20",
                    "dateFinRqth": None,
                    "source": "FRANCE TRAVAIL",
                    "topValiditeRQTH": True,
                },
                {"certification_period": InclusiveDateRange(datetime.date(2024, 1, 20))},
                id="certified_for_ever_null_end_at",
            ),
        ],
    )
    @respx.mock
    def test_rqth(self, json_response, expected_data):
        respx.post(settings.API_ESD["BASE_URL"] + Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR).respond(
            200, json=RESPONSES[Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][ResponseKind.CERTIFIED]
        )

        respx.get(settings.API_ESD["BASE_URL"] + Endpoints.RQTH).respond(200, json=json_response)

        # The RQTH certification calls two endpoints: rechercher_usager and donnees_rqth.
        # Use a context manager to reuse the same HTTP client.
        # See BasePoleEmploiApiClient._httpx_client
        with self.api_client as client:
            data = client.rqth(jobseeker_profile=JobSeekerProfileFactory())
        for key, value in expected_data.items():
            assert data[key] == value
        assert data["raw_response"] == json_response
