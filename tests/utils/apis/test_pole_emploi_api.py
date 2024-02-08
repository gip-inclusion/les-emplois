import json
import math
import time

import httpx
import pytest
import respx
from django.core.cache import caches

from itou.utils.apis.pole_emploi import (
    CACHE_API_TOKEN_KEY,
    REFRESH_TOKEN_MARGIN_SECONDS,
    PoleEmploiAPIBadResponse,
    PoleEmploiApiClient,
    PoleEmploiAPIException,
    PoleEmploiRateLimitException,
)
from itou.utils.mocks import pole_emploi as pole_emploi_api_mocks
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class PoleEmploiAPIClientTest(TestCase):
    CACHE_EXPIRY = 3600

    def setUp(self) -> None:
        super().setUp()
        self.api_client = PoleEmploiApiClient("https://pe.fake", "https://auth.fr", "foobar", "pe-secret")
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": self.CACHE_EXPIRY}
        )

    @respx.mock
    def test_get_token_nominal(self):
        start = math.floor(time.time())  # Ignore microseconds.
        self.api_client._refresh_token()
        cache = caches["failsafe"]
        assert cache.get(CACHE_API_TOKEN_KEY) == "foo batman"
        redis_client = cache._cache.get_client()
        expiry = redis_client.expiretime(cache.make_key(CACHE_API_TOKEN_KEY))
        assert start + self.CACHE_EXPIRY - REFRESH_TOKEN_MARGIN_SECONDS <= expiry <= start + self.CACHE_EXPIRY

    @respx.mock
    def test_get_token_fails(self):
        job_seeker = JobSeekerFactory()
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").mock(
            side_effect=httpx.ConnectTimeout
        )
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
            )
        assert ctx.value.error_code == "http_error"

    @respx.mock
    def test_recherche_individu_certifie_api_nominal(self):
        job_seeker = JobSeekerFactory()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=pole_emploi_api_mocks.API_RECHERCHE_RESULT_KNOWN
        )
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
        )
        assert id_national == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"

        # now with weird payloads
        job_seeker.first_name = "marié%{-christine}  aéïèêë " + "a" * 50
        job_seeker.last_name = "gh'îkñ Bind-n'qici " + "b" * 50
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
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
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
            )
        assert ctx.value.response_code == "R010"

    @respx.mock
    def test_recherche_individu_certifie_retryable_errors(self):
        job_seeker = JobSeekerFactory()

        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(401, json="")
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
            )
        assert ctx.value.error_code == 401

        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(429, json="")
        with pytest.raises(PoleEmploiRateLimitException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
            )

        job_seeker = JobSeekerFactory()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").mock(
            side_effect=httpx.ConnectTimeout
        )
        with pytest.raises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.jobseeker_profile.nir
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

    @respx.mock
    def test_appellations(self):
        respx.get("https://pe.fake/rome/v1/appellation?champs=code,libelle,metier(code)").respond(
            200,
            json=pole_emploi_api_mocks.API_APPELLATIONS,
        )
        assert self.api_client.appellations() == pole_emploi_api_mocks.API_APPELLATIONS
