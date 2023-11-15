import datetime

import httpx
import pytest
import respx
from django.conf import settings
from django.contrib import auth
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertRedirects

from itou.external_data.apis import pe_connect
from itou.external_data.models import ExternalDataImport
from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.openid_connect.models import InvalidKindException
from itou.openid_connect.pe_connect import constants
from itou.openid_connect.pe_connect.models import PoleEmploiConnectState, PoleEmploiConnectUserData
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from tests.users.factories import JobSeekerFactory, UserFactory
from tests.utils.test import reload_module


PEAMU_USERINFO = {
    "given_name": "Angela Claire Louise",
    "family_name": "DUBOIS",
    "gender": "female",
    "email": "wossewodda-3728@yopmail.com",
    "sub": "b6048e95bb134ec5b1d1e1fa69f287172e91722b9354d637a1bcf2ebb0fd2ef5v1",
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(
    client,
    expected_route="dashboard:index",
    user_info=None,
):
    # No session is created with PEAMU in contrary to Inclusion Connect
    # so there's no use to go through pe_connect:authorize

    token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(constants.PE_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_info = user_info or PEAMU_USERINFO
    respx.get(constants.PE_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, json=user_info))

    fake_api_data = {
        "dateDeNaissance": "2000-01-01T00:00:00Z",
        "codeStatutIndividu": "1",
        "codePostal": "75001",
        "beneficiairePrestationSolidarite": True,
    }
    for api in [
        pe_connect.ESD_COORDS_API,
        pe_connect.ESD_STATUS_API,
        pe_connect.ESD_BIRTHDATE_API,
        pe_connect.ESD_COMPENSATION_API,
    ]:
        respx.get(f"{settings.API_ESD['BASE_URL']}/{api}").mock(return_value=httpx.Response(200, json=fake_api_data))

    state = PoleEmploiConnectState.save_state()
    url = reverse("pe_connect:callback")
    response = client.get(url, data={"code": "123", "state": state})
    assertRedirects(response, reverse(expected_route))
    return response


TEST_SETTINGS = {
    "PEAMU_AUTH_BASE_URL": "https://peamu.auth.fake.url",
    "API_ESD": {
        "BASE_URL": "https://some.auth.domain",
        "AUTH_BASE_URL": "https://some-authentication-domain.fr",
        "KEY": "somekey",
        "SECRET": "somesecret",
    },
}


class TestPoleEmploiConnect:
    @pytest.fixture(autouse=True)
    def setup(self):
        with override_settings(**TEST_SETTINGS):
            with reload_module(constants):
                yield

    def test_state_delete(self):
        state = PoleEmploiConnectState.objects.create(state="foo")

        PoleEmploiConnectState.objects.cleanup()

        state.refresh_from_db()
        assert state is not None

        # Set creation time for the state so that the state is expired
        state.created_at = timezone.now() - OIDC_STATE_CLEANUP * 2
        state.save()

        PoleEmploiConnectState.objects.cleanup()

        with pytest.raises(PoleEmploiConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_verification(self):
        state = PoleEmploiConnectState.save_state()
        assert PoleEmploiConnectState.get_from_state(state).is_valid()

    def test_state_is_valid(self):
        with freeze_time("2022-09-13 12:00:01"):
            state = PoleEmploiConnectState.save_state()
            assert isinstance(state, str)
            assert PoleEmploiConnectState.get_from_state(state).is_valid()

            state = PoleEmploiConnectState.save_state()
        with freeze_time("2022-10-13 12:00:01"):
            assert not PoleEmploiConnectState.get_from_state(state).is_valid()

    def test_authorize(self, client):
        url = reverse("pe_connect:authorize")
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.PE_CONNECT_ENDPOINT_AUTHORIZE)

    def test_create_user(self):
        """
        Nominal scenario: there is no user with the PEAMU id or PEAMU email
        that is sent, so we create one
        """
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)
        assert not User.objects.filter(username=peamu_user_data.username).exists()
        assert not User.objects.filter(email=peamu_user_data.email).exists()
        user, created = peamu_user_data.create_or_update_user()
        assert created
        assert user.last_name == PEAMU_USERINFO["family_name"]
        assert user.first_name == PEAMU_USERINFO["given_name"]
        assert user.external_data_source_history[0]["source"] == "PEC"
        assert user.identity_provider == IdentityProvider.PE_CONNECT
        assert user.kind == UserKind.JOB_SEEKER

        # Update user
        peamu_user_data.last_name = "DUPUIS"
        user, created = peamu_user_data.create_or_update_user()
        assert not created
        assert user.last_name == "DUPUIS"
        assert user.identity_provider == IdentityProvider.PE_CONNECT

    def test_create_user_with_already_existing_peamu_id(self):
        """
        If there already is an existing user with this PEAMU id, we do not create it again,
        we use it and we update it
        """
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)
        JobSeekerFactory(
            username=peamu_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=IdentityProvider.PE_CONNECT,
        )
        user, created = peamu_user_data.create_or_update_user()
        assert not created
        assert user.last_name == PEAMU_USERINFO["family_name"]
        assert user.first_name == PEAMU_USERINFO["given_name"]
        assert user.external_data_source_history[0]["source"] == "PEC"
        assert user.identity_provider == IdentityProvider.PE_CONNECT

    def test_create_user_with_already_existing_peamu_id_but_from_other_sso(self):
        """
        If there already is an existing user with this PEAMU id, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)
        JobSeekerFactory(
            username=peamu_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=IdentityProvider.FRANCE_CONNECT,
            email="random@email.com",
        )
        with pytest.raises(ValidationError):
            peamu_user_data.create_or_update_user()

    def test_create_django_user_with_already_existing_peamu_email_django(self):
        """
        If there already is an existing user from Django with email PEAMU sent us
        we use it and we update it
        """
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)
        JobSeekerFactory(email=peamu_user_data.email, identity_provider=IdentityProvider.DJANGO)
        user, created = peamu_user_data.create_or_update_user()
        assert not created
        assert user.last_name == PEAMU_USERINFO["family_name"]
        assert user.first_name == PEAMU_USERINFO["given_name"]
        assert user.username == PEAMU_USERINFO["sub"]
        assert user.identity_provider == IdentityProvider.PE_CONNECT
        assert user.external_data_source_history != {}

    def test_create_django_user_with_already_existing_peamu_email_other_sso(self):
        """
        If there already is an existing user with email PEAMU sent us, we do not create it again,
        we use it but we do not update it
        """
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)
        JobSeekerFactory(email=peamu_user_data.email, identity_provider=IdentityProvider.FRANCE_CONNECT)
        user, created = peamu_user_data.create_or_update_user()
        assert not created
        assert user.last_name != PEAMU_USERINFO["family_name"]
        assert user.first_name != PEAMU_USERINFO["given_name"]
        assert user.username != PEAMU_USERINFO["sub"]
        # We did not fill this data using external data, so it is not set
        assert not user.external_data_source_history
        assert user.identity_provider != IdentityProvider.PE_CONNECT

    def test_create_or_update_user_raise_too_many_kind_exception(self):
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)

        for kind in [UserKind.PRESCRIBER, UserKind.EMPLOYER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=peamu_user_data.username, email=peamu_user_data.email, kind=kind)

            with pytest.raises(InvalidKindException):
                peamu_user_data.create_or_update_user()

            user.delete()

    def test_callback_no_code(self, client):
        url = reverse("pe_connect:callback")
        response = client.get(url)
        assert response.status_code == 302

    def test_callback_no_state(self, client):
        url = reverse("pe_connect:callback")
        response = client.get(url, data={"code": "123"})
        assert response.status_code == 302

    def test_callback_invalid_state(self, client):
        url = reverse("pe_connect:callback")
        response = client.get(url, data={"code": "123", "state": "000"})
        assert response.status_code == 302

    @pytest.mark.django_db(transaction=True)
    @respx.mock
    def test_callback(self, client):
        response = mock_oauth_dance(client)
        user = User.objects.get()
        assert user.email == PEAMU_USERINFO["email"]
        assert user.first_name == PEAMU_USERINFO["given_name"]
        assert user.last_name == PEAMU_USERINFO["family_name"]
        assert user.username == PEAMU_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.identity_provider == IdentityProvider.PE_CONNECT
        assert user.nir == ""
        assert user.birthdate == datetime.date(2000, 1, 1)
        assert user.externaldataimport_set.pe_sources().get().status == ExternalDataImport.STATUS_OK
        assertRedirects(response, reverse("dashboard:index"))

        user.birthdate = datetime.date(2001, 1, 1)
        user.save()

        # Don't call import_user_pe_data on second login (and don't update user data)
        response = mock_oauth_dance(client)
        assert user.externaldataimport_set.pe_sources().count() == 1
        assert user.birthdate == datetime.date(2001, 1, 1)

    @respx.mock
    def test_callback_no_email(self, client):
        user_info = PEAMU_USERINFO.copy()
        del user_info["email"]
        mock_oauth_dance(client, user_info=user_info, expected_route="pe_connect:no_email")
        assert not User.objects.exists()

    @respx.mock
    def test_callback_with_nir(self, client):
        # Complete signup with NIR is tested in JobSeekerSignupTest.test_job_seeker_nir
        nir = "141068078200557"
        client.post(reverse("signup:job_seeker_nir"), {"nir": nir})
        assert global_constants.ITOU_SESSION_NIR_KEY in list(client.session.keys())
        assert client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        mock_oauth_dance(client)
        user = User.objects.get()
        assert user.email == PEAMU_USERINFO["email"]
        assert user.nir == nir

    @respx.mock
    def test_callback_redirect_on_too_many_kind_exception(self, client):
        peamu_user_data = PoleEmploiConnectUserData.from_user_info(PEAMU_USERINFO)

        for kind in [UserKind.PRESCRIBER, UserKind.EMPLOYER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=peamu_user_data.username, email=peamu_user_data.email, kind=kind)
            mock_oauth_dance(client, expected_route=f"login:{kind}")
            user.delete()

    def test_logout_no_id_token(self, client):
        url = reverse("pe_connect:logout")
        response = client.get(url + "?")
        assert response.status_code == 400
        assert response.json()["message"] == "Le paramètre « id_token » est manquant."

    def test_logout(self, client):
        url = reverse("pe_connect:logout")
        response = client.get(url, data={"id_token": "123"})
        expected_url = (
            f"{constants.PE_CONNECT_ENDPOINT_LOGOUT}?id_token_hint=123&"
            "redirect_uri=http%3A%2F%2Flocalhost:8000%2Fsearch%2Femployers"
        )
        assertRedirects(response, expected_url, fetch_redirect_response=False)

    @respx.mock
    def test_django_account_logout_from_peamu(self, client):
        """
        When ac IC user wants to log out from his local account,
        he should be logged out too from IC.
        """
        response = mock_oauth_dance(client)
        assert auth.get_user(client).is_authenticated
        # Follow the redirection.
        response = client.get(response.url)
        logout_url = reverse("account_logout")
        assertContains(response, logout_url)
        assert client.session.get(constants.PE_CONNECT_SESSION_TOKEN)

        response = client.post(logout_url)
        expected_redirection = reverse("pe_connect:logout")
        # For simplicity, exclude GET params. They are tested elsewhere anyway..
        assert response.url.startswith(expected_redirection)

        response = client.get(response.url)
        # The following redirection is tested in self.test_logout_with_redirection
        assert response.status_code == 302
        assert not auth.get_user(client).is_authenticated
