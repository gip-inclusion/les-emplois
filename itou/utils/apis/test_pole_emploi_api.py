import datetime
import json

import httpx
import respx
from django.test import TestCase
from django.utils import timezone

from itou.job_applications.factories import JobApplicationFactory
from itou.users.factories import JobSeekerFactory
from itou.utils.apis.pole_emploi import PoleEmploiAPIBadResponse, PoleEmploiApiClient, PoleEmploiAPIException
from itou.utils.mocks import pole_emploi as pole_emploi_api_mocks


class PoleEmploiAPIClientTest(TestCase):
    def setUp(self) -> None:
        self.api_client = PoleEmploiApiClient(
            "https://api.pe.fake", "https://some-authentication-domain.fr", "foobar", "pe-secret"
        )
        respx.post(self.api_client.token_url).respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
        )

    @respx.mock
    def test_get_token_nominal(self):
        now = timezone.now()
        self.api_client._refresh_token(at=now)
        self.assertEqual(self.api_client.token, "foo batman")
        self.assertEqual(self.api_client.expires_at, now + datetime.timedelta(seconds=3600))

    @respx.mock
    def test_get_token_fails(self):
        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.token_url).mock(side_effect=httpx.ConnectTimeout)
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.error_code, "http_error")

    @respx.mock
    def test_recherche_individu_certifie_api_nominal(self):
        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.recherche_individu_url).respond(
            200, json=pole_emploi_api_mocks.API_RECHERCHE_RESULT_KNOWN
        )
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
        )
        self.assertEqual(id_national, "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ")

        # now with weird payloads
        job_seeker.first_name = "marié%{-christine}  aéïèêë " + "a" * 50
        job_seeker.last_name = "gh'îkñ Bind-n'qici " + "b" * 50
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
        )
        payload = json.loads(respx.calls.last.request.content)
        self.assertEqual(payload["nomNaissance"], "GH'IKN BIND-N'QICI BBBBBB")  # 25 chars
        self.assertEqual(payload["prenom"], "MARIE-CHRISTI")  # 13 chars

    @respx.mock
    def test_recherche_individu_certifie_individual_api_errors(self):
        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.recherche_individu_url).respond(200, json=pole_emploi_api_mocks.API_RECHERCHE_ERROR)
        with self.assertRaises(PoleEmploiAPIBadResponse) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.response_code, "R010")

    @respx.mock
    def test_recherche_individu_certifie_retryable_errors(self):
        job_seeker = JobSeekerFactory()

        respx.post(self.api_client.recherche_individu_url).respond(401, json="")
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.error_code, 401)

        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.recherche_individu_url).mock(side_effect=httpx.ConnectTimeout)
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.error_code, "http_error")

    @respx.mock
    def test_mise_a_jour_pass_iae_success_with_approval_accepted(self):
        """
        Nominal scenario: an approval is **accepted**
        HTTP 200 + codeSortie = S001 is the only way mise_a_jour_pass_iae does not raise.
        """
        job_application = JobApplicationFactory(with_approval=True)
        respx.post(self.api_client.mise_a_jour_url).respond(200, json=pole_emploi_api_mocks.API_MAJPASS_RESULT_OK)
        # we really don't care about the arguments there
        self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

    @respx.mock
    def test_mise_a_jour_pass_iae_failure(self):
        job_application = JobApplicationFactory(with_approval=True)
        # non-S001 codeSortie
        respx.post(self.api_client.mise_a_jour_url).respond(200, json=pole_emploi_api_mocks.API_MAJPASS_RESULT_ERROR)
        with self.assertRaises(PoleEmploiAPIBadResponse):
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

        # timeout
        respx.post(self.api_client.mise_a_jour_url).mock(side_effect=httpx.ConnectTimeout)
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")
        self.assertEqual(ctx.exception.error_code, "http_error")

        # auth failed
        respx.post(self.api_client.mise_a_jour_url).respond(401, json={})
        with self.assertRaises(PoleEmploiAPIException):
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")
        self.assertEqual(ctx.exception.error_code, "http_error")
