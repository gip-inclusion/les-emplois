import datetime

import httpx
import pytest
import respx
from django.contrib import auth, messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertRedirects

from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.openid_connect.france_connect import constants
from itou.openid_connect.france_connect.models import FranceConnectState, FranceConnectUserData
from itou.openid_connect.models import EmailInUseException, InvalidKindException, MultipleSubSameEmailException
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.users.factories import JobSeekerFactory, UserFactory
from tests.utils.test import reload_module


FC_USERINFO = {
    "given_name": "Angela Claire Louise",
    "family_name": "DUBOIS",
    "birthdate": "1962-08-24",
    "gender": "female",
    "birthplace": "75107",
    "birthcountry": "99100",
    "email": "wossewodda-3728@yopmail.com",
    "address": {
        "country": "France",
        "formatted": "France Paris 75107 20 avenue de Ségur",
        "locality": "Paris",
        "postal_code": "75107",
        "street_address": "20 avenue de Ségur",
    },
    "phone_number": "123456789",
    "sub": "b6048e95bb134ec5b1d1e1fa69f287172e91722b9354d637a1bcf2ebb0fd2ef5v1",
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(client, expected_route="dashboard:index"):
    # No session is created with France Connect in contrary to Inclusion Connect
    # so there's no use to go through france_connect:authorize

    token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(constants.FRANCE_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_info = FC_USERINFO.copy()
    respx.get(constants.FRANCE_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, json=user_info))

    state = FranceConnectState.save_state()
    url = reverse("france_connect:callback")
    response = client.get(url, data={"code": "123", "state": state}, follow=True)
    assertRedirects(response, reverse(expected_route))
    return response


class TestFranceConnect:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.FRANCE_CONNECT_BASE_URL = "https://france.connect.fake"
        settings.FRANCE_CONNECT_CLIENT_ID = "FC_CLIENT_ID_123"
        settings.FRANCE_CONNECT_CLIENT_SECRET = "FC_CLIENT_SECRET_123"
        with reload_module(constants):
            yield

    def test_state_delete(self):
        state = FranceConnectState.objects.create(state="foo")

        FranceConnectState.objects.cleanup()

        state.refresh_from_db()
        assert state is not None

        # Set creation time for the state so that the state is expired
        state.created_at = timezone.now() - OIDC_STATE_CLEANUP * 2
        state.save()

        FranceConnectState.objects.cleanup()

        with pytest.raises(FranceConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_verification(self):
        state = FranceConnectState.save_state()
        assert FranceConnectState.get_from_state(state).is_valid()

    def test_state_is_valid(self):
        with freeze_time("2022-09-13 12:00:01"):
            state = FranceConnectState.save_state()
            assert isinstance(state, str)
            assert FranceConnectState.get_from_state(state).is_valid()

            state = FranceConnectState.save_state()
        with freeze_time("2022-10-13 12:00:01"):
            assert not FranceConnectState.get_from_state(state).is_valid()

    def test_authorize(self, client):
        url = reverse("france_connect:authorize")
        response = client.get(url, follow=False)
        # Don't use assertRedirects to avoid fetch
        assert response.url.startswith(constants.FRANCE_CONNECT_ENDPOINT_AUTHORIZE)

    def test_create_django_user(self):
        """
        Nominal scenario: there is no user with the FranceConnect id or FranceConnect email
        that is sent, so we create one
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        assert not User.objects.filter(username=fc_user_data.username).exists()
        assert not User.objects.filter(email=fc_user_data.email).exists()
        user, created = fc_user_data.create_or_update_user()
        assert created
        assert user.last_name == FC_USERINFO["family_name"]
        assert user.first_name == FC_USERINFO["given_name"]
        assert user.phone == FC_USERINFO["phone_number"]
        assert user.jobseeker_profile.birthdate == datetime.date.fromisoformat(FC_USERINFO["birthdate"])
        assert user.address_line_1 == FC_USERINFO["address"]["street_address"]
        assert user.post_code == FC_USERINFO["address"]["postal_code"]
        assert user.city == FC_USERINFO["address"]["locality"]

        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT
        assert user.kind == UserKind.JOB_SEEKER

        # Update user
        fc_user_data.last_name = "DUPUIS"
        fc_user_data.birthdate = datetime.date(1926, 7, 9)
        user, created = fc_user_data.create_or_update_user()
        assert not created
        assert user.last_name == "DUPUIS"
        assert user.jobseeker_profile.birthdate == datetime.date(1926, 7, 9)
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT

    def test_create_django_user_optional_fields(self):
        fc_info = FC_USERINFO | {
            "given_name": "",
            "family_name": "",
            "birthdate": "",
            "phone_number": "",
            "address": {
                "street_address": "",
                "postal_code": "",
                "locality": "",
            },
        }
        fc_user_data = FranceConnectUserData.from_user_info(fc_info)
        user, created = fc_user_data.create_or_update_user()
        assert created
        assert not user.first_name
        assert not user.post_code
        assert not user.jobseeker_profile.birthdate
        assert not user.phone
        assert not user.address_line_1
        assert not user.post_code

    def test_create_django_user_country_other_than_france(self):
        """
        Nominal scenario: there is no user with the FranceConnect id or FranceConnect email
        that is sent, so we create one
        """
        user_info = FC_USERINFO | {
            "address": {
                "country": "Colombia",
                "locality": "Granada",
                "postal_code": "",
                "street_address": "Parque central",
            },
        }
        fc_user_data = FranceConnectUserData.from_user_info(user_info)
        assert not User.objects.filter(username=fc_user_data.username).exists()
        assert not User.objects.filter(email=fc_user_data.email).exists()
        user, created = fc_user_data.create_or_update_user()
        assert created
        assert user.last_name == FC_USERINFO["family_name"]
        assert user.first_name == FC_USERINFO["given_name"]
        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT
        assert user.address_line_1 == ""
        assert user.post_code == ""
        assert user.city == ""

    def test_create_django_user_with_already_existing_fc_id(self):
        """
        If there already is an existing user with this FranceConnectId, we do not create it again,
        we use it and we update it
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        JobSeekerFactory(
            username=fc_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=IdentityProvider.FRANCE_CONNECT,
        )
        user, created = fc_user_data.create_or_update_user()
        assert not created
        assert user.last_name == FC_USERINFO["family_name"]
        assert user.first_name == FC_USERINFO["given_name"]
        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT

    def test_create_django_user_with_already_existing_fc_id_but_from_other_sso(self):
        """
        If there already is an existing user with this FranceConnectId, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        JobSeekerFactory(
            username=fc_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=IdentityProvider.DJANGO,
            email="random@email.com",
        )
        with pytest.raises(ValidationError):
            fc_user_data.create_or_update_user()

    def test_create_or_update_user_raise_invalid_kind_exception(self):
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)

        for kind in UserKind.professionals():
            user = UserFactory(username=fc_user_data.username, email=fc_user_data.email, kind=kind)

            with pytest.raises(InvalidKindException):
                fc_user_data.create_or_update_user()

            user.delete()

    def test_update_readonly_with_certified_criteria(self, caplog):
        job_seeker = JobSeekerFactory(
            username=FC_USERINFO["sub"],
            identity_provider=IdentityProvider.FRANCE_CONNECT,
            born_in_france=True,
        )
        IAESelectedAdministrativeCriteriaFactory(eligibility_diagnosis__job_seeker=job_seeker, certified=True)
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        user, created = fc_user_data.create_or_update_user()
        assert created is False
        assert user.last_name == job_seeker.last_name
        assert user.first_name == job_seeker.first_name
        assert user.phone == FC_USERINFO["phone_number"]
        assert user.jobseeker_profile.birthdate == job_seeker.jobseeker_profile.birthdate
        assert user.address_line_1 == FC_USERINFO["address"]["street_address"]
        assert user.post_code == FC_USERINFO["address"]["postal_code"]
        assert user.city == FC_USERINFO["address"]["locality"]
        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT
        assert user.kind == UserKind.JOB_SEEKER
        assert (
            f"Not updating fields birthdate, first_name, last_name on job seeker pk={job_seeker.pk} "
            "because their identity has been certified." in caplog.messages
        )

    def test_callback_no_code(self, client):
        url = reverse("france_connect:callback")
        response = client.get(url)
        assert response.status_code == 302

    def test_callback_no_state(self, client):
        url = reverse("france_connect:callback")
        response = client.get(url, data={"code": "123"})
        assert response.status_code == 302

    def test_callback_invalid_state(self, client):
        url = reverse("france_connect:callback")
        response = client.get(url, data={"code": "123", "state": "000"})
        assert response.status_code == 302

    @respx.mock
    def test_callback(self, client):
        # New created job seeker has no title and is redirected to complete its infos
        mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        assert User.objects.count() == 1
        user = User.objects.get(email=FC_USERINFO["email"])
        assert user.first_name == FC_USERINFO["given_name"]
        assert user.last_name == FC_USERINFO["family_name"]
        assert user.username == FC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT

    @respx.mock
    def test_callback_redirect_on_invalid_kind_exception(self, client):
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)

        for kind in UserKind.professionals():
            user = UserFactory(username=fc_user_data.username, email=fc_user_data.email, kind=kind)
            mock_oauth_dance(client, expected_route=f"login:{kind}")
            user.delete()

    @respx.mock
    def test_callback_redirect_on_email_in_use_exception(self, client, snapshot):
        # EmailInUseException raised by the email conflict
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        JobSeekerFactory(email=fc_user_data.email, identity_provider=IdentityProvider.PE_CONNECT, for_snapshot=True)

        # Test redirection and modal content
        response = mock_oauth_dance(client, expected_route="signup:choose_user_kind")
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])

    @respx.mock
    def test_callback_redirect_on_sub_conflict(self, client, snapshot):
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        user = JobSeekerFactory(
            username="another_sub", email=fc_user_data.email, identity_provider=IdentityProvider.FRANCE_CONNECT
        )

        # Test redirection and modal content
        response = mock_oauth_dance(client, expected_route="login:job_seeker")
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])

        # If we force the update
        user.allow_next_sso_sub_update = True
        user.save()
        response = mock_oauth_dance(client)
        assertMessages(response, [])
        user.refresh_from_db()
        assert user.allow_next_sso_sub_update is False
        assert user.username == fc_user_data.username

        # If we allow the update again, but the sub does change, we still disable allow_next_sso_sub_update
        user.allow_next_sso_sub_update = True
        user.save()
        response = mock_oauth_dance(client)
        assertMessages(response, [])
        user.refresh_from_db()
        assert user.allow_next_sso_sub_update is False

    def test_logout_no_id_token(self, client):
        url = reverse("france_connect:logout")
        response = client.get(url + "?")
        assert response.status_code == 400
        assert response.json()["message"] == "Le paramètre « id_token » est manquant."

    def test_logout(self, client):
        url = reverse("france_connect:logout")
        response = client.get(url, data={"id_token": "123"})
        expected_url = (
            f"{constants.FRANCE_CONNECT_ENDPOINT_LOGOUT}?id_token_hint=123&state=&"
            "post_logout_redirect_uri=http%3A%2F%2Flocalhost:8000%2Fsearch%2Femployers"
        )
        assertRedirects(response, expected_url, fetch_redirect_response=False)

    @respx.mock
    def test_django_account_logout_from_fc(self, client):
        """
        When ac IC user wants to log out from his local account,
        he should be logged out too from IC.
        """
        # New created job seeker has no title and is redirected to complete its infos
        response = mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        assert auth.get_user(client).is_authenticated
        logout_url = reverse("account_logout")
        assertContains(response, logout_url)
        assert client.session.get(constants.FRANCE_CONNECT_SESSION_TOKEN)

        response = client.post(logout_url)
        expected_redirection = reverse("france_connect:logout")
        # For simplicity, exclude GET params. They are tested elsewhere anyway..
        assert response.url.startswith(expected_redirection)

        response = client.get(response.url)
        # The following redirection is tested in self.test_logout_with_redirection
        assert response.status_code == 302
        assert not auth.get_user(client).is_authenticated


@pytest.mark.parametrize("identity_provider", [IdentityProvider.DJANGO, IdentityProvider.PE_CONNECT])
def test_create_fc_user_with_already_existing_email_fails(identity_provider):
    """
    In OIDC, SSO provider + username represents unicity.
    However, we require that emails are unique as well.
    """
    fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
    JobSeekerFactory(
        username="another_username",
        email=fc_user_data.email,
        identity_provider=identity_provider,
    )
    with pytest.raises(EmailInUseException):
        fc_user_data.create_or_update_user()


def test_create_fc_user_with_already_existing_fc_email_fails():
    """
    In OIDC, SSO provider + username represents unicity.
    However, we require that emails are unique as well.
    """
    fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
    JobSeekerFactory(
        username="another_username",
        email=fc_user_data.email,
        identity_provider=IdentityProvider.FRANCE_CONNECT,
    )
    with pytest.raises(MultipleSubSameEmailException):
        fc_user_data.create_or_update_user()
