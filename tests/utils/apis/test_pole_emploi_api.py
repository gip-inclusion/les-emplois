import datetime
import json
import math
import time

import httpx
import pytest
import respx
from django.core.cache import caches
from django_redis import get_redis_connection

from itou.utils.apis.enums import PEApiRechercheIndividuExitCode
from itou.utils.apis.pole_emploi import (
    REFRESH_TOKEN_MARGIN_SECONDS,
    IdentityNotCertified,
    MultipleUsersReturned,
    PoleEmploiAPIBadResponse,
    PoleEmploiAPIException,
    PoleEmploiRateLimitException,
    PoleEmploiRoyaumeAgentAPIClient,
    PoleEmploiRoyaumePartenaireApiClient,
    UserDoesNotExist,
)
from itou.utils.mocks import pole_emploi as pole_emploi_api_mocks
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
            json=pole_emploi_api_mocks.API_APPELLATIONS,
        )
        respx.get("https://pe.fake/offresdemploi/v2/referentiel/naturesContrats").respond(
            200, json=pole_emploi_api_mocks.API_REFERENTIEL_NATURE_CONTRATS
        )

        # Connection pooling
        client = PoleEmploiRoyaumePartenaireApiClient("https://pe.fake", "https://auth.fr", "foobar", "pe-secret")
        with client:
            first_client = client._get_httpx_client()
            assert client._refresh_token() == "foo batman"
            assert client.appellations() == pole_emploi_api_mocks.API_APPELLATIONS
            assert client.referentiel("naturesContrats") == pole_emploi_api_mocks.API_REFERENTIEL_NATURE_CONTRATS
            assert first_client is client._get_httpx_client()

        # Outside a context manager…
        # …an error is raised if we try to reuse a client previously created by a context manager…
        with pytest.raises(RuntimeError, match="Cannot send a request, as the client has been closed"):
            client.appellations()

        # …but if no context manager was used before, a new HTTPX client is created for each new request.
        client = PoleEmploiRoyaumePartenaireApiClient("https://pe.fake", "https://auth.fr", "foobar", "pe-secret")
        assert client._refresh_token() == "foo batman"
        first_client = client._get_httpx_client()
        assert client.appellations() == pole_emploi_api_mocks.API_APPELLATIONS
        assert first_client is not client._get_httpx_client()

    @respx.mock
    def test_recherche_individu_certifie_api_nominal(self):
        job_seeker = JobSeekerFactory()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=pole_emploi_api_mocks.API_RECHERCHE_RESULT_KNOWN
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
            200, json=pole_emploi_api_mocks.API_RECHERCHE_ERROR
        )
        with pytest.raises(PoleEmploiAPIBadResponse) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name,
                job_seeker.last_name,
                job_seeker.jobseeker_profile.birthdate,
                job_seeker.jobseeker_profile.nir,
            )
        assert ctx.value.response_code == PEApiRechercheIndividuExitCode.R010
        assert ctx.value.response_data == pole_emploi_api_mocks.API_RECHERCHE_ERROR

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
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(
            200, json=pole_emploi_api_mocks.API_MAJPASS_RESULT_OK
        )
        # we really don't care about the arguments there
        self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

    @respx.mock
    def test_mise_a_jour_pass_iae_failure(self):
        job_application = JobApplicationFactory(with_approval=True)
        # non-S001 codeSortie
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(
            200, json=pole_emploi_api_mocks.API_MAJPASS_RESULT_ERROR
        )
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
            200, json=pole_emploi_api_mocks.API_REFERENTIEL_NATURE_CONTRATS
        )
        assert self.api_client.referentiel("naturesContrats") == pole_emploi_api_mocks.API_REFERENTIEL_NATURE_CONTRATS

    @respx.mock
    def test_offres(self):
        respx.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT&range=0-1").respond(
            206,  # test code 206 as we already know that 200 is tested through the other tests
            json={"resultats": pole_emploi_api_mocks.API_OFFRES},
        )
        assert self.api_client.offres(natureContrat="FT", range="0-1") == pole_emploi_api_mocks.API_OFFRES
        respx.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=&range=100-140").respond(
            204
        )
        assert self.api_client.offres(range="100-140") == []

        EA_OFFERS = [{**offer, "entrepriseAdaptee": True} for offer in pole_emploi_api_mocks.API_OFFRES]

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
            json=pole_emploi_api_mocks.API_APPELLATIONS,
        )
        assert self.api_client.appellations() == pole_emploi_api_mocks.API_APPELLATIONS

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
    def setup_method(self):
        self.api_client = PoleEmploiRoyaumeAgentAPIClient(
            base_url="https://pe.fake",
            auth_base_url="https://auth.fr",
            key="client_id",
            secret="client_secret",
        )
        json_response = {
            "token_type": "Bearer",
            "access_token": "Catwoman",
            "scope": "client_id h2a rechercheusager profil_accedant api_donnees-rqthv1 api_rechercher-usagerv2",
            "expires_in": self.CACHE_EXPIRY,
        }
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent").respond(200, json=json_response)

    @respx.mock
    def test_refresh_token(self):
        # This method is already tested on TestPoleEmploiRoyaumePartenaireApiClient.
        token = self.api_client._refresh_token()
        assert token == "Bearer Catwoman"

    @respx.mock
    def test_request_caches_token(self):
        respx.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            200, json={"sample": "data"}
        )
        self.api_client._request("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir")
        assert caches["failsafe"].get(PoleEmploiRoyaumeAgentAPIClient.CACHE_API_TOKEN_KEY) == "Bearer Catwoman"

    @respx.mock
    def test_request_http_request_headers(self):
        mock = respx.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            200, json={"sample": "data"}
        )
        self.api_client._request("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir")
        headers = mock.calls[-1].request.headers

        expected_headers = {
            "Authorization": "Bearer Catwoman",
            "Content-Type": "application/json",
            "pa-nom-agent": "<string>",
            "pa-prenom-agent": "<string>",
            "pa-identifiant-agent": "<string>",
        }
        for key, value in expected_headers.items():
            assert headers[key] == value

        # test additional headers.
        additional_headers = {"ft-jeton-usager": "something-very-long"}
        self.api_client._request(
            "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir",
            additional_headers=additional_headers,
        )

        headers = mock.calls[-1].request.headers

        expected_headers = {
            "Authorization": "Bearer Catwoman",
            "Content-Type": "application/json",
            "pa-nom-agent": "<string>",
            "pa-prenom-agent": "<string>",
            "pa-identifiant-agent": "<string>",
            **additional_headers,
        }
        for key, value in expected_headers.items():
            assert headers[key] == value

    @pytest.mark.parametrize(
        "json_response,http_status_code,expected_error,expected_error_message",
        [
            pytest.param(
                {
                    "codeRetour": "R997",
                    "message": "Une erreur de validation s'est produite",
                    "topIdentiteCertifiee": "null",
                    "jetonUsager": "null",
                },
                400,
                PoleEmploiAPIBadResponse,
                r"PoleEmploiAPIBadResponse\(code=400\)",
                id="400",
            ),
            pytest.param(
                {
                    "codeRetour": "R001",
                    "message": "Accès non autorisé",
                    "topIdentiteCertifiee": "null",
                    "jetonUsager": "null",
                },
                403,
                PoleEmploiAPIBadResponse,
                r"PoleEmploiAPIBadResponse\(code=403\)",
                id="403",
            ),
            pytest.param(
                {
                    "codeRetour": "R998",
                    "message": "Un service a répondu en erreur",
                    "topIdentiteCertifiee": "null",
                    "jetonUsager": "null",
                },
                500,
                PoleEmploiAPIException,
                r"PoleEmploiAPIException\(code=500\)",
                id="500",
            ),
            pytest.param(
                {
                    "codeRetour": "R999",
                    "message": "Service indisponible, veuillez réessayer ultérieurement",
                    "topIdentiteCertifiee": "null",
                    "jetonUsager": "null",
                },
                503,
                PoleEmploiAPIException,
                r"PoleEmploiAPIException\(code=503\)",
                id="503",
            ),
        ],
    )
    @respx.mock
    def test_request_status_codes(self, json_response, http_status_code, expected_error, expected_error_message):
        respx.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            http_status_code, json=json_response
        )
        with pytest.raises(expected_error, match=expected_error_message):
            self.api_client._request(
                "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir",
            )

    @respx.mock
    def test_rechercher_usager_by_birthdate_and_nir(self):
        json_response = {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        }
        respx.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            200, json=json_response
        )
        jeton_usager = self.api_client.rechercher_usager(jobseeker_profile=JobSeekerProfileFactory())
        assert jeton_usager == "a_long_token"

    @respx.mock
    def test_rechercher_usager_by_pole_emploi_id(self):
        json_response = {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        }
        respx.post("https://pe.fake/rechercher-usager/v2/usagers/par-numero-francetravail").respond(
            200, json=json_response
        )
        jobseeker_profile = JobSeekerProfileFactory(birthdate=None, nir="", pole_emploi_id="12345678901")
        jeton_usager = self.api_client.rechercher_usager(jobseeker_profile=jobseeker_profile)
        assert jeton_usager == "a_long_token"

    @pytest.mark.parametrize(
        "json_response,exception_raised,exception_pattern",
        [
            pytest.param(
                {
                    "codeRetour": "S002",
                    "message": "Aucun approchant trouvé",
                    "jetonUsager": None,
                    "topIdentiteCertifiee": None,
                },
                UserDoesNotExist,
                r"UserDoesNotExist",
                id="user_does_not_exist",
            ),
            pytest.param(
                {
                    "codeRetour": "S001",
                    "message": "Approchant trouvé",
                    "jetonUsager": "a_long_token",
                    "topIdentiteCertifiee": "N",
                },
                IdentityNotCertified,
                r"IdentityNotCertified",
                id="identity_not_certified",
            ),
            pytest.param(
                {
                    "codeRetour": "S003",
                    "message": "Plusieurs usagers trouvés",
                    "jetonUsager": None,
                    "topIdentiteCertifiee": None,
                },
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
        url = "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir"
        respx.post(url).respond(200, json=json_response)
        with pytest.raises(exception_raised, match=exception_pattern):
            self.api_client.rechercher_usager(jobseeker_profile=JobSeekerProfileFactory())

    @respx.mock
    def test_rechercher_usager_calls_nir_endpoint(self):
        json_response = {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        }
        mock_birthdate_nir = respx.post(
            "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir"
        ).respond(200, json=json_response)
        mock_pole_emploi_id = respx.post(
            "https://pe.fake/rechercher-usager/v2/usagers/par-numero-francetravail"
        ).respond(200, json=json_response)

        token = self.api_client.rechercher_usager(jobseeker_profile=JobSeekerProfileFactory())
        assert token == "a_long_token"
        assert mock_birthdate_nir.called
        assert not mock_pole_emploi_id.called

    @respx.mock
    def test_rechercher_usager_calls_pole_emploi_id_endpoint(self):
        json_response = {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        }
        mock_birthdate_nir = respx.post(
            "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir"
        ).respond(200, json=json_response)
        mock_pole_emploi_id = respx.post(
            "https://pe.fake/rechercher-usager/v2/usagers/par-numero-francetravail"
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
                {
                    "dateDebutRqth": "2024-01-20",
                    "dateFinRqth": "2030-01-20",
                    "source": "FRANCE TRAVAIL",
                    "topValiditeRQTH": True,
                },
                {
                    "is_certified": True,
                    "start_at": datetime.date(2024, 1, 20),
                    "end_at": datetime.date(2030, 1, 20),
                },
                id="certified",
            ),
            pytest.param(
                {
                    "dateDebutRqth": "",
                    "dateFinRqth": "",
                    "source": "",
                    "topValiditeRQTH": False,
                },
                {
                    "is_certified": False,
                    "start_at": None,
                    "end_at": None,
                },
                id="not_certified",
            ),
            pytest.param(
                {
                    "dateDebutRqth": "2024-01-20",
                    "dateFinRqth": "9999-12-31",
                    "source": "FRANCE TRAVAIL",
                    "topValiditeRQTH": True,
                },
                {
                    "is_certified": True,
                    "start_at": datetime.date(2024, 1, 20),
                    "end_at": None,
                },
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
                {
                    "is_certified": True,
                    "start_at": datetime.date(2024, 1, 20),
                    "end_at": None,
                },
                id="certified_for_ever_null_end_at",
            ),
        ],
    )
    @respx.mock
    def test_certify_rqth(self, json_response, expected_data):
        rechercher_usager_json_response = {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        }
        respx.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            200, json=rechercher_usager_json_response
        )

        respx.get("https://pe.fake/donnees-rqth/v1/rqth").respond(200, json=json_response)

        # The RQTH certification calls two endpoints: rechercher_usager and donnees_rqth.
        # Use a context manager to reuse the same HTTP client.
        # See BasePoleEmploiApiClient._httpx_client
        with self.api_client as client:
            data = client.certify_rqth(jobseeker_profile=JobSeekerProfileFactory())
        for key, value in expected_data.items():
            assert data[key] == value
        assert data["raw_response"] == json_response
