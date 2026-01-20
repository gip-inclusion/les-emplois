import base64
import datetime
import hashlib
import random
import time
import uuid

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.utils import int_to_bytes
from django.conf import settings
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
from itou.users.enums import IdentityProvider, Title, UserKind
from itou.users.models import User
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.users.factories import JobSeekerFactory, UserFactory
from tests.utils.testing import reload_module


FC_USERINFO = {
    "gender": "female",
    "given_name": "Angela Claire Louise",
    "given_name_array": ["Angela", "Claire", "Louise"],
    "family_name": "DUBOIS",
    "email": "wossewodda-3728@yopmail.com",
    "birthdate": "1962-08-24",
    "sub": "d303068c700ea93405ae193550a7d99be03744c08be08901e8e1c180869b2f54v1",
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(client, expected_route="dashboard:index", matching_nonces=True, valid_id_token=True):
    # No session is created with France Connect in contrary to ProConnect
    # so there's no use to go through france_connect:authorize
    id_token_nonce = str(uuid.uuid4())
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_numbers = private_key.public_key().public_numbers()
    jwk_json = {
        "keys": [
            {
                "kty": "EC",
                "use": "sig",
                "kid": "pkcs11:ES256:hsm",
                "alg": "ES256",
                "crv": "P-256",
                "x": base64.urlsafe_b64encode(int_to_bytes(public_key_numbers.x, 32)).decode().rstrip("="),
                "y": base64.urlsafe_b64encode(int_to_bytes(public_key_numbers.y, 32)).decode().rstrip("="),
            }
        ]
    }
    respx.get(constants.FRANCE_CONNECT_ENDPOINT_JWKS).mock(return_value=httpx.Response(200, json=jwk_json))

    now = int(time.time())
    access_token = "aw9EMEBXYME57xmj-ZZYPPC9yxSRfK-A3MPCL56zysd"
    access_token_hash = hashlib.sha256(access_token.encode()).digest()
    common_jwt_content = {
        "sub": FC_USERINFO["sub"],
        "aud": settings.FRANCE_CONNECT_CLIENT_ID,
        "exp": now + 60,
        "iat": now,
        "iss": "https://fcp-low.sbx.dev-franceconnect.fr/api/v2",
    }

    id_token_content = {
        "auth_time": now,
        "acr": "eidas1",
        "nonce": id_token_nonce,
        "at_hash": base64.urlsafe_b64encode(access_token_hash[:16]).decode().rstrip("="),
        **common_jwt_content,
    }
    id_token = jwt.encode(id_token_content, private_key, algorithm="ES256", headers={"kid": "pkcs11:ES256:hsm"})

    token_json = {
        "access_token": access_token,
        "expires_in": 60,
        "id_token": id_token if valid_id_token else "invalid_id_token",
        "scope": "openid gender given_name family_name email birthdate",
        "token_type": "Bearer",
    }
    respx.post(constants.FRANCE_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_data = {
        **FC_USERINFO,
        **common_jwt_content,
    }
    user_response = jwt.encode(user_data, private_key, algorithm="ES256", headers={"kid": "pkcs11:ES256:hsm"})
    respx.get(constants.FRANCE_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, content=user_response))

    state = FranceConnectState.save_state(nonce=id_token_nonce if matching_nonces else "other_nonce")
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
        fc_state = FranceConnectState.objects.last()
        assert f"state={fc_state.state}" in response.url
        assert fc_state.nonce is not None
        assert f"nonce={fc_state.nonce}" in response.url

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
        assert user.jobseeker_profile.birthdate == datetime.date.fromisoformat(FC_USERINFO["birthdate"])

        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT
        assert user.kind == UserKind.JOB_SEEKER
        assert user.title == Title.MME

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
            "gender": "",
        }
        fc_user_data = FranceConnectUserData.from_user_info(fc_info)
        user, created = fc_user_data.create_or_update_user()
        assert created
        assert not user.first_name
        assert not user.title
        assert not user.jobseeker_profile.birthdate

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
            title=Title.M,
        )
        user, created = fc_user_data.create_or_update_user()
        assert not created
        assert user.last_name == FC_USERINFO["family_name"]
        assert user.first_name == FC_USERINFO["given_name"]
        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT
        assert user.title == Title.MME

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
            title=Title.M,
        )
        IAESelectedAdministrativeCriteriaFactory(eligibility_diagnosis__job_seeker=job_seeker, criteria_certified=True)
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        user, created = fc_user_data.create_or_update_user()
        assert created is False
        assert user.last_name == job_seeker.last_name
        assert user.first_name == job_seeker.first_name
        assert user.jobseeker_profile.birthdate == job_seeker.jobseeker_profile.birthdate
        assert user.external_data_source_history[0]["source"] == "FC"
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT
        assert user.kind == UserKind.JOB_SEEKER
        assert (
            f"Not updating fields birthdate, first_name, last_name, title on job seeker pk={job_seeker.pk} "
            "because their identity has been certified." in caplog.messages
        )

    def test_callback_nothing(self, client):
        url = reverse("france_connect:callback")
        response = client.get(url)
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "Le paramètre « state » fourni par FranceConnect et nécessaire à votre authentification "
                        "n’est pas valide."
                    ),
                )
            ],
        )

    def test_callback_no_state(self, client):
        url = reverse("france_connect:callback")
        response = client.get(url, data={"code": "123"})
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "Le paramètre « state » fourni par FranceConnect et nécessaire à votre authentification "
                        "n’est pas valide."
                    ),
                )
            ],
        )

    def test_callback_invalid_state(self, client):
        url = reverse("france_connect:callback")
        response = client.get(url, data={"code": "123", "state": "000"})
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "Le paramètre « state » fourni par FranceConnect et nécessaire à votre authentification "
                        "n’est pas valide."
                    ),
                )
            ],
        )

    def test_callback_no_code(self, client):
        state = FranceConnectState.save_state()
        url = reverse("france_connect:callback")
        response = client.get(url, data={"state": state})
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "FranceConnect n’a pas transmis le paramètre « code » nécessaire à votre authentification.",
                )
            ],
        )

    def test_callback_error_access_denied(self, client):
        state = FranceConnectState.save_state()
        url = reverse("france_connect:callback")
        response = client.get(url, data={"state": state, "error": "access_denied"})
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Votre connexion à FranceConnect a échoué. Veuillez réessayer.",
                )
            ],
        )

    def test_callback_error_france_connect_unavailable(self, client):
        state = FranceConnectState.save_state()
        url = reverse("france_connect:callback")
        response = client.get(
            url, data={"state": state, "error": random.choice(["server_error", "temporarily_unavailable"])}
        )
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "FranceConnect est temporairement indisponible. Veuillez réessayer ultérieurement.",
                )
            ],
        )

    def test_callback_error_mistake(self, client, caplog):
        error_code = random.choice(["invalid_scope", "invalid_request", "unknown_error_code"])
        state = FranceConnectState.save_state()
        url = reverse("france_connect:callback")
        response = client.get(
            url,
            data={
                "state": state,
                "error": error_code,
                "error_description": "Frobulateur en panne",
            },
        )
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La connexion avec FranceConnect est actuellement impossible. "
                        "Veuillez utiliser un autre mode de connexion."
                    ),
                )
            ],
        )

        assert [(record.levelname, record.getMessage()) for record in caplog.records] == [
            (
                "ERROR",
                f"FranceConnect callback with state={state} - code=None - error={error_code} "
                "- error_description=Frobulateur en panne",
            ),
            ("INFO", "HTTP 302 Found"),
        ]

    @respx.mock
    def test_callback(self, client):
        # Redirect to edit_user_info because FC does not provide address_line_1, city and post_code
        mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        assert User.objects.count() == 1
        user = User.objects.get(email=FC_USERINFO["email"])
        assert user.first_name == FC_USERINFO["given_name"]
        assert user.last_name == FC_USERINFO["family_name"]
        assert user.username == FC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.identity_provider == IdentityProvider.FRANCE_CONNECT

    @respx.mock
    def test_callback_mismatched_nonce(self, client):
        # Redirect to edit_user_info because FC does not provide address_line_1, city and post_code
        response = mock_oauth_dance(client, expected_route="login:job_seeker", matching_nonces=False)
        assert User.objects.count() == 0
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Le jeton d’authentification de FranceConnect est invalide.",
                )
            ],
        )

    @respx.mock
    def test_callback_invalid_id_token(self, client):
        # Redirect to edit_user_info because FC does not provide address_line_1, city and post_code
        response = mock_oauth_dance(client, expected_route="login:job_seeker", valid_id_token=False)
        assert User.objects.count() == 0
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Le jeton d’authentification de FranceConnect est invalide.",
                )
            ],
        )

    @respx.mock
    def test_callback_redirect_on_inactive_user(self, client):
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)

        user = UserFactory(
            username=fc_user_data.username,
            email=fc_user_data.email,
            kind=UserKind.JOB_SEEKER,
            is_active=False,
            identity_provider=IdentityProvider.FRANCE_CONNECT,
        )
        response = mock_oauth_dance(client, expected_route="login:job_seeker")
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La connexion via FranceConnect a fonctionné mais le compte lié sur les Emplois de l’inclusion"
                        " est désactivé. Veuillez vous rapprocher du support pour débloquer la situation en suivant "
                        '<a href="https://aide.emplois.inclusion.beta.gouv.fr/hc/fr">ce lien</a> et en leur '
                        f"fournissant l’identifiant public de ce compte : {user.public_id}."
                    ),
                )
            ],
        )

    @respx.mock
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
        # Redirect to edit_user_info because FC does not provide address_line_1, city and post_code
        response = mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        assertMessages(response, [])
        user.refresh_from_db()
        assert user.allow_next_sso_sub_update is False
        assert user.username == fc_user_data.username

        # If we allow the update again, but the sub does change, we still disable allow_next_sso_sub_update
        user.allow_next_sso_sub_update = True
        user.save()
        # Redirect to edit_user_info because FC does not provide address_line_1, city and post_code
        response = mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
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
        response = client.get(url, data={"id_token": "123", "state": "some_state"})
        expected_url = (
            f"{constants.FRANCE_CONNECT_ENDPOINT_LOGOUT}?id_token_hint=123&state=some_state&"
            "post_logout_redirect_uri=http%3A%2F%2Flocalhost:8000%2Fsearch%2Femployers"
        )
        assertRedirects(response, expected_url, fetch_redirect_response=False)

    @respx.mock
    def test_django_account_logout_from_fc(self, client):
        """
        When ac IC user wants to log out from his local account,
        he should be logged out too from IC.
        """
        # Redirect to edit_user_info because FC does not provide address_line_1, city and post_code
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
