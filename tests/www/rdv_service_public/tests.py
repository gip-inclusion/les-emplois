import httpx
import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertMessages, assertRedirects

from itou.rdv_service_public.models import AppointmentProposal, OAuthToken
from itou.utils.apis import rdv_service_public
from itou.utils.mocks.rdv_service_public import RDV_SERVICE_PUBLIC_RDV_PLAN_BODY, RDV_SERVICE_PUBLIC_TOKEN_BODY
from itou.www.rdv_service_public.views import OAUTH_SESSION_KEY, REQUEST_FAILED_MESSAGE, UNAVAILABLE_MESSAGE
from tests.job_applications.factories import JobApplicationFactory
from tests.rdv_service_public.factories import OAuthTokenFactory
from tests.users.factories import EmployerFactory


BASE_URL = "https://rdv-service-public.fake"
TOKEN_URL = f"{BASE_URL}/oauth/token"
ME_URL = f"{BASE_URL}/api/v1/agents/me"
RDV_PLANS_URL = f"{BASE_URL}/api/v1/rdv_plans"
RDV_PLAN_URL = RDV_SERVICE_PUBLIC_RDV_PLAN_BODY["rdv_plan"]["url"]
CALLBACK_URL = "http://testserver/rdv-service-public/oauth/callback"


@pytest.fixture(autouse=True)
def rdvsp_settings(settings):
    settings.RDV_SERVICE_PUBLIC_BASE_URL = BASE_URL
    settings.RDV_SERVICE_PUBLIC_CLIENT_ID = "client-id"
    settings.RDV_SERVICE_PUBLIC_CLIENT_SECRET = "S3cr3t!"
    return settings


@pytest.fixture
def job_application():
    return JobApplicationFactory(
        to_company__allow_rdv_service_public=True,
        sent_by_authorized_prescriber=True,
        job_seeker__email="jacques.henry@example.com",
        job_seeker__phone="0601020304",
    )


@pytest.fixture
def employer(job_application):
    return job_application.to_company.members.get()


def propose_url(job_application):
    return reverse("rdv_service_public:propose_appointment", kwargs={"job_application_id": job_application.pk})


def job_application_url(job_application):
    path = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    return f"http://testserver{path}"


def mock_create_rdv_plan(respx_mock, job_application, access_token):
    job_seeker = job_application.job_seeker
    return respx_mock.post(
        RDV_PLANS_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "user": {
                "external_id": f"{job_seeker.public_id}-{job_application.to_company.pk}",
                "first_name": job_seeker.first_name,
                "last_name": job_seeker.last_name,
                "email": "jacques.henry@example.com",
                "phone_number": "0601020304",
                "address": job_seeker.address_on_one_line,
            },
            "return_url": job_application_url(job_application),
            "dossier_url": job_application_url(job_application),
        },
    ).respond(201, json=RDV_SERVICE_PUBLIC_RDV_PLAN_BODY)


def assert_proposal_recorded(job_application, employer):
    proposal = AppointmentProposal.objects.get()
    assert proposal.job_application == job_application
    assert proposal.company == job_application.to_company
    assert proposal.job_seeker == job_application.job_seeker
    assert proposal.created_by == employer
    assert proposal.rdv_service_public_plan_id == 1234
    assert proposal.rdv_service_public_user_id == 5678


class TestProposeAppointment:
    def test_propose(self, client, respx_mock, job_application, employer):
        OAuthTokenFactory(user=employer, access_token="access-token")
        mock_create_rdv_plan(respx_mock, job_application, "access-token")
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assertRedirects(response, RDV_PLAN_URL, fetch_redirect_response=False)
        assert_proposal_recorded(job_application, employer)

    def test_link_account_first(self, client, respx_mock, job_application, employer):
        # No route: any request to RDV Service Public would fail the test
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        oauth_session = client.session[OAUTH_SESSION_KEY]
        assert oauth_session["job_application_id"] == str(job_application.pk)
        authorize_url = rdv_service_public.get_oauth_client().get_authorize_url(
            redirect_uri=CALLBACK_URL, state=oauth_session["state"]
        )
        assertRedirects(response, authorize_url, fetch_redirect_response=False)
        assert not AppointmentProposal.objects.exists()

    def test_revoked_token(self, client, respx_mock, job_application, employer):
        OAuthTokenFactory(user=employer)
        respx_mock.post(RDV_PLANS_URL).respond(401)
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assert response.status_code == 302
        assert response.url.startswith(f"{BASE_URL}/oauth/authorize?")
        assert not OAuthToken.objects.exists()

    @pytest.mark.parametrize(
        "api_response, message",
        [
            (httpx.Response(500), UNAVAILABLE_MESSAGE),
            # The domain of return_url is not declared in the OAuth application
            (
                httpx.Response(
                    422, json={"errors": {"return_url": [{"error": "n'est pas un nom de domaine autorisé"}]}}
                ),
                REQUEST_FAILED_MESSAGE,
            ),
        ],
        ids=["unavailable", "refused"],
    )
    def test_rdv_service_public_error(self, client, respx_mock, job_application, employer, api_response, message):
        OAuthTokenFactory(user=employer)
        respx_mock.post(RDV_PLANS_URL).mock(return_value=api_response)
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(response, [messages.Message(messages.ERROR, message)])
        assert not AppointmentProposal.objects.exists()

    def test_invalid_phone_number(self, client, respx_mock, job_application, employer):
        OAuthTokenFactory(user=employer)
        respx_mock.post(RDV_PLANS_URL).respond(422, json={"errors": {"phone_number": [{"error": "invalid"}]}})
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "RDV Service Public n'accepte pas le numéro de téléphone du candidat. "
                    "Corrigez-le via Modifier, puis recommencez.",
                )
            ],
        )
        assert not AppointmentProposal.objects.exists()

    @pytest.mark.parametrize(
        "api_response, message",
        [
            (httpx.Response(500), UNAVAILABLE_MESSAGE),
            (httpx.Response(401, json={"error": "invalid_client"}), REQUEST_FAILED_MESSAGE),
        ],
        ids=["unavailable", "refused"],
    )
    def test_refresh_error(self, client, respx_mock, job_application, employer, api_response, message):
        OAuthTokenFactory(user=employer, expires_at=timezone.now())
        respx_mock.post(TOKEN_URL).mock(return_value=api_response)
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(response, [messages.Message(messages.ERROR, message)])
        assert OAuthToken.objects.exists()

    def test_refresh_expired_token(self, client, respx_mock, job_application, employer):
        OAuthTokenFactory(user=employer, expires_at=timezone.now())
        respx_mock.post(TOKEN_URL).respond(200, json=RDV_SERVICE_PUBLIC_TOKEN_BODY)
        # The new access token is used right away
        mock_create_rdv_plan(respx_mock, job_application, "access-token")
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assertRedirects(response, RDV_PLAN_URL, fetch_redirect_response=False)
        assert OAuthToken.objects.get().access_token == "access-token"

    def test_refresh_refused(self, client, respx_mock, job_application, employer):
        OAuthTokenFactory(user=employer, expires_at=timezone.now())
        respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_grant"})
        client.force_login(employer)

        response = client.post(propose_url(job_application))
        assert response.status_code == 302
        assert response.url.startswith(f"{BASE_URL}/oauth/authorize?")
        assert not OAuthToken.objects.exists()

    def test_job_seeker_without_email(self, client, respx_mock):
        job_application = JobApplicationFactory(
            to_company__allow_rdv_service_public=True,
            sent_by_authorized_prescriber=True,
            job_seeker__email=None,
        )
        client.force_login(job_application.to_company.members.get())

        response = client.post(propose_url(job_application))
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Le candidat doit avoir une adresse e-mail pour que vous puissiez lui proposer un rendez-vous.",
                )
            ],
        )

    @pytest.mark.parametrize(
        "field, value",
        [("allow_rdv_service_public", False), ("rdv_solidarites_id", 1234)],
        ids=["not_allowed", "rdv_insertion_experiment"],
    )
    def test_company_cannot_use_rdv_service_public(self, client, job_application, employer, field, value):
        setattr(job_application.to_company, field, value)
        job_application.to_company.save()
        client.force_login(employer)

        assert client.post(propose_url(job_application)).status_code == 404

    def test_not_a_member_of_the_company(self, client, job_application):
        client.force_login(EmployerFactory())
        assert client.post(propose_url(job_application)).status_code == 404

    @pytest.mark.parametrize("profile", ["prescriber", "job_seeker"])
    def test_not_an_employer(self, client, profile_login, job_application, profile):
        profile_login(profile, job_application)
        assert client.post(propose_url(job_application)).status_code == 403


class TestOAuthCallback:
    url = reverse("rdv_service_public:oauth_callback")

    def start_oauth(self, client, job_application):
        session = client.session
        session[OAUTH_SESSION_KEY] = {"state": "the-state", "job_application_id": str(job_application.pk)}
        session.save()

    def mock_get_token(self, respx_mock):
        respx_mock.post(
            TOKEN_URL,
            data={
                "client_id": "client-id",
                "client_secret": "S3cr3t!",
                "grant_type": "authorization_code",
                "code": "the-code",
                "redirect_uri": CALLBACK_URL,
            },
        ).respond(200, json=RDV_SERVICE_PUBLIC_TOKEN_BODY)

    def mock_get_me(self, respx_mock, email):
        respx_mock.get(ME_URL, headers={"Authorization": "Bearer access-token"}).respond(
            200, json={"agent": {"id": 42, "first_name": "Alice", "last_name": "Martin", "email": email}}
        )

    def test_callback(self, client, respx_mock, job_application, employer):
        client.force_login(employer)
        self.start_oauth(client, job_application)
        self.mock_get_token(respx_mock)
        # The case of the email doesn't matter
        self.mock_get_me(respx_mock, email=employer.email.upper())
        mock_create_rdv_plan(respx_mock, job_application, "access-token")

        response = client.get(self.url, {"code": "the-code", "state": "the-state"})
        assertRedirects(response, RDV_PLAN_URL, fetch_redirect_response=False)
        token = OAuthToken.objects.get(user=employer)
        assert token.access_token == "access-token"
        assert token.refresh_token == "refresh-token"
        assert token.rdv_service_public_agent_id == 42
        assert_proposal_recorded(job_application, employer)
        assert OAUTH_SESSION_KEY not in client.session

    @pytest.mark.parametrize("with_oauth_session", [False, True], ids=["no_session", "wrong_state"])
    def test_invalid_state(self, client, respx_mock, job_application, employer, with_oauth_session):
        client.force_login(employer)
        if with_oauth_session:
            self.start_oauth(client, job_application)

        response = client.get(self.url, {"code": "the-code", "state": "another-state"})
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)
        assertMessages(
            response, [messages.Message(messages.ERROR, "Une erreur technique est survenue. Merci de recommencer.")]
        )
        assert OAUTH_SESSION_KEY not in client.session

    def test_access_denied(self, client, respx_mock, job_application, employer):
        client.force_login(employer)
        self.start_oauth(client, job_application)

        response = client.get(self.url, {"error": "access_denied", "state": "the-state"})
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Vous devez autoriser La plateforme de l’inclusion à accéder à RDV Service Public "
                    "pour proposer un rendez-vous.",
                )
            ],
        )
        assert not OAuthToken.objects.exists()

    def test_authorization_error(self, client, respx_mock, job_application, employer):
        client.force_login(employer)
        self.start_oauth(client, job_application)

        response = client.get(self.url, {"error": "invalid_scope", "state": "the-state"})
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(response, [messages.Message(messages.ERROR, UNAVAILABLE_MESSAGE)])

    @pytest.mark.parametrize(
        "api_response, message",
        [
            (httpx.Response(500), UNAVAILABLE_MESSAGE),
            (httpx.Response(401, json={"error": "invalid_client"}), REQUEST_FAILED_MESSAGE),
        ],
        ids=["unavailable", "refused"],
    )
    def test_rdv_service_public_error(self, client, respx_mock, job_application, employer, api_response, message):
        client.force_login(employer)
        self.start_oauth(client, job_application)
        respx_mock.post(TOKEN_URL).mock(return_value=api_response)

        response = client.get(self.url, {"code": "the-code", "state": "the-state"})
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(response, [messages.Message(messages.ERROR, message)])
        assert not OAuthToken.objects.exists()

    def test_agent_of_a_colleague(self, client, respx_mock, job_application, employer):
        client.force_login(employer)
        self.start_oauth(client, job_application)
        self.mock_get_token(respx_mock)
        # A colleague is logged in RDV Service Public in this browser
        self.mock_get_me(respx_mock, email="bob@example.com")

        response = client.get(self.url, {"code": "the-code", "state": "the-state"})
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Vous êtes connecté à RDV Service Public avec le compte bob@example.com. "
                    "Déconnectez-vous de RDV Service Public, puis recommencez.",
                )
            ],
        )
        assert not OAuthToken.objects.exists()
        assert not AppointmentProposal.objects.exists()

    def test_token_revoked_right_after_linking(self, client, respx_mock, job_application, employer):
        client.force_login(employer)
        self.start_oauth(client, job_application)
        self.mock_get_token(respx_mock)
        self.mock_get_me(respx_mock, email=employer.email)
        respx_mock.post(RDV_PLANS_URL).respond(401)

        response = client.get(self.url, {"code": "the-code", "state": "the-state"})
        # No new authorization, to avoid a redirection loop
        assertRedirects(response, job_application_url(job_application), fetch_redirect_response=False)
        assertMessages(response, [messages.Message(messages.ERROR, UNAVAILABLE_MESSAGE)])
        assert not OAuthToken.objects.exists()
