import dataclasses
import json
from operator import itemgetter
from unittest import mock
from urllib.parse import quote, urlencode

import httpx
import pytest
import respx
from django.contrib import auth, messages
from django.contrib.auth import get_user
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertRedirects

from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.openid_connect.inclusion_connect import constants
from itou.openid_connect.inclusion_connect.models import (
    InclusionConnectEmployerData,
    InclusionConnectPrescriberData,
    InclusionConnectState,
)
from itou.openid_connect.inclusion_connect.views import InclusionConnectSession
from itou.openid_connect.models import InvalidKindException
from itou.users import enums as users_enums
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.urls import add_url_params, get_absolute_url
from tests.openid_connect.inclusion_connect.test import InclusionConnectBaseTestCase
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)
from tests.utils.test import assertMessages


pytestmark = pytest.mark.ignore_template_errors

OIDC_USERINFO = {
    "given_name": "Michel",
    "family_name": "AUDIARD",
    "email": "michel@lestontons.fr",
    "sub": "af6b26f9-85cd-484e-beb9-bea5be13e30f",
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(
    client,
    user_kind,
    previous_url=None,
    next_url=None,
    expected_redirect_url=None,
    user_email=None,
    user_info_email=None,
    channel=None,
    register=True,
    other_client=None,
):
    assert user_kind, "Letting this filed empty is not allowed"
    # Authorize params depend on user kind.
    authorize_params = {
        "user_kind": user_kind,
        "previous_url": previous_url,
        "next_url": next_url,
        "user_email": user_email,
        "channel": channel,
        "register": register,
    }
    authorize_params = {k: v for k, v in authorize_params.items() if v}

    # Calling this view is mandatory to start a new session.
    authorize_url = f"{reverse('inclusion_connect:authorize')}?{urlencode(authorize_params)}"
    response = client.get(authorize_url)
    if register:
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_REGISTER)
    else:
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)

    # User is logged out from IC when an error happens during the oauth dance.
    respx.get(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(200)

    token_json = {"access_token": "access_token", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(constants.INCLUSION_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_info = OIDC_USERINFO.copy()
    if user_info_email:
        user_info["email"] = user_info_email
    respx.get(constants.INCLUSION_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, json=user_info))

    state = client.session[constants.INCLUSION_CONNECT_SESSION_KEY]["state"]
    url = reverse("inclusion_connect:callback")
    callback_client = other_client or client
    response = callback_client.get(url, data={"code": "123", "state": state})
    # If a expected_redirect_url was provided, check it redirects there
    # If not, the default redirection is next_url if provided, or welcoming_tour for new users
    expected = expected_redirect_url or next_url or reverse("welcoming_tour:index")
    assertRedirects(response, expected, fetch_redirect_response=False)
    return response


class InclusionConnectModelTest(InclusionConnectBaseTestCase):
    def test_state_delete(self):
        state = InclusionConnectState.objects.create(state="foo")

        InclusionConnectState.objects.cleanup()

        state.refresh_from_db()
        assert state is not None

        # Set creation time for the state so that the state is expired
        state.created_at = timezone.now() - OIDC_STATE_CLEANUP * 2
        state.save()

        InclusionConnectState.objects.cleanup()

        with pytest.raises(InclusionConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_is_valid(self):
        with freeze_time("2022-09-13 12:00:01"):
            state = InclusionConnectState.save_state()
            assert isinstance(state, str)
            assert InclusionConnectState.get_from_state(state).is_valid()

            state = InclusionConnectState.save_state()
        with freeze_time("2022-10-13 12:00:01"):
            assert not InclusionConnectState.get_from_state(state).is_valid()

    def test_create_user_from_user_info(self):
        """
        Nominal scenario: there is no user with the InclusionConnect ID or InclusionConnect email
        that is sent, so we create one.
        Similar to france_connect.tests.FranceConnectTest.test_create_django_user
        but with more tests.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        assert not User.objects.filter(username=ic_user_data.username).exists()
        assert not User.objects.filter(email=ic_user_data.email).exists()

        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            user, created = ic_user_data.create_or_update_user()
        assert created
        assert user.email == OIDC_USERINFO["email"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.username == OIDC_USERINFO["sub"]

        user.refresh_from_db()
        expected = [
            {
                "field_name": field.name,
                "value": getattr(user, field.name),
                "source": "IC",
                "created_at": now_str,
            }
            for field in dataclasses.fields(ic_user_data)
        ]
        assert sorted(user.external_data_source_history, key=itemgetter("field_name")) == sorted(
            expected, key=itemgetter("field_name")
        )

    def test_create_user_from_user_info_with_already_existing_id(self):
        """
        If there already is an existing user with this InclusionConnect id, we do not create it again,
        we use it and we update it.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        PrescriberFactory(
            username=ic_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT,
        )
        user, created = ic_user_data.create_or_update_user()
        assert not created
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.external_data_source_history[0]["source"] == "IC"

    def test_create_user_from_user_info_with_already_existing_id_but_from_other_sso(self):
        """
        If there already is an existing user with this InclusionConnect id, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        PrescriberFactory(
            username=ic_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.DJANGO,
            email="random@email.com",
        )
        with pytest.raises(ValidationError):
            ic_user_data.create_or_update_user()

    def test_get_existing_user_with_same_email_django(self):
        """
        If there already is an existing django user with email InclusionConnect sent us, we do not create it again,
        We user it and we update it with the data form the identity_provider.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        PrescriberFactory(email=ic_user_data.email, identity_provider=users_enums.IdentityProvider.DJANGO)
        user, created = ic_user_data.create_or_update_user()
        assert not created
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    def test_update_user_from_user_info(self):
        user = PrescriberFactory(**dataclasses.asdict(InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)))
        ic_user = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        new_ic_user = InclusionConnectPrescriberData(
            first_name="Jean", last_name="Gabin", username=ic_user.username, email="jean@lestontons.fr"
        )
        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            user, created = new_ic_user.create_or_update_user()
        assert not created

        user.refresh_from_db()
        expected = [
            {
                "field_name": field.name,
                "value": getattr(user, field.name),
                "source": "IC",
                "created_at": now_str,
            }
            for field in dataclasses.fields(ic_user)
        ]
        assert sorted(user.external_data_source_history, key=itemgetter("field_name")) == sorted(
            expected, key=itemgetter("field_name")
        )

    def test_create_or_update_prescriber_raise_too_many_kind_exception(self):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        for kind in [UserKind.JOB_SEEKER, UserKind.EMPLOYER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=kind)

            with pytest.raises(InvalidKindException):
                ic_user_data.create_or_update_user()

            user.delete()

    def test_create_or_update_employer_raise_too_many_kind_exception(self):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)

        for kind in [UserKind.JOB_SEEKER, UserKind.PRESCRIBER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=kind)

            with pytest.raises(InvalidKindException):
                ic_user_data.create_or_update_user()

            user.delete()


class InclusionConnectAuthorizeViewTest(InclusionConnectBaseTestCase):
    def test_authorize_endpoint(self):
        url = reverse("inclusion_connect:authorize")
        response = self.client.get(url, follow=False)
        self.assertRedirects(response, reverse("search:siaes_home"))

        url = f"{reverse('inclusion_connect:authorize')}?user_kind={UserKind.PRESCRIBER}"
        response = self.client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in self.client.session

    def test_authorize_endpoint_for_registration(self):
        url = reverse("inclusion_connect:authorize")
        response = self.client.get(url, follow=False)
        self.assertRedirects(response, reverse("search:siaes_home"))

        url = f"{reverse('inclusion_connect:authorize')}?user_kind={UserKind.PRESCRIBER}&register=true"
        response = self.client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_REGISTER)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in self.client.session

    def test_authorize_endpoint_with_params(self):
        email = "porthos@touspourun.com"
        params = {"user_email": email, "user_kind": UserKind.PRESCRIBER, "channel": "invitation"}
        url = f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}"
        response = self.client.get(url, follow=False)
        assert f"login_hint={quote(email)}" in response.url
        ic_state = InclusionConnectState.get_from_state(
            self.client.session[constants.INCLUSION_CONNECT_SESSION_KEY]["state"]
        )
        assert ic_state.data["user_email"] == email

    def test_authorize_check_user_kind(self):
        forbidden_user_kinds = [UserKind.ITOU_STAFF, UserKind.LABOR_INSPECTOR, UserKind.JOB_SEEKER]
        for kind in forbidden_user_kinds:
            with self.subTest(kind=kind):
                url = f"{reverse('inclusion_connect:authorize')}?user_kind={kind}"
                response = self.client.get(url)
                self.assertRedirects(response, reverse("search:siaes_home"))


class InclusionConnectCallbackViewTest(InclusionConnectBaseTestCase):
    @respx.mock
    def test_callback_invalid_state(self):
        token_json = {"access_token": "access_token", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
        respx.post(constants.INCLUSION_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

        url = reverse("inclusion_connect:callback")
        response = self.client.get(url, data={"code": "123", "state": "000"})
        assert response.status_code == 302

    def test_callback_no_state(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url, data={"code": "123"})
        assert response.status_code == 302

    def test_callback_no_code(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url)
        assert response.status_code == 302

    @respx.mock
    def test_callback_prescriber_created(self):
        ### User does not exist.
        mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        assert User.objects.count() == 1
        user = User.objects.get(email=OIDC_USERINFO["email"])
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.kind == "prescriber"
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    @respx.mock
    def test_callback_employer_created(self):
        ### User does not exist.
        mock_oauth_dance(self.client, UserKind.EMPLOYER)
        assert User.objects.count() == 1
        user = User.objects.get(email=OIDC_USERINFO["email"])
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.kind == UserKind.EMPLOYER
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    @respx.mock
    def test_callback_existing_django_user(self):
        # User created with django already exists on Itou but some attributes differs.
        # Update all fields
        PrescriberFactory(
            first_name="Bernard",
            last_name="Blier",
            username="bernard_blier",
            email=OIDC_USERINFO["email"],
            identity_provider=users_enums.IdentityProvider.DJANGO,
        )
        mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        assert User.objects.count() == 1
        user = User.objects.get(email=OIDC_USERINFO["email"])
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    @respx.mock
    def test_callback_allows_employer_on_prescriber_login_only(self):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=UserKind.EMPLOYER)

        response = mock_oauth_dance(
            self.client,
            UserKind.PRESCRIBER,
            expected_redirect_url=add_url_params(
                reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:siaes_home")}
            ),
        )
        response = self.client.get(reverse("search:siaes_home"))
        self.assertContains(response, "existe déjà avec cette adresse e-mail")
        self.assertContains(response, "pour devenir prescripteur sur la plateforme")
        assert get_user(self.client).is_authenticated is False

        response = mock_oauth_dance(self.client, UserKind.PRESCRIBER, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.EMPLOYER
        assert get_user(self.client).is_authenticated is True

    @respx.mock
    def test_callback_allows_prescriber_on_employer_login_only(self):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)
        user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=UserKind.PRESCRIBER)

        response = mock_oauth_dance(
            self.client,
            UserKind.EMPLOYER,
            expected_redirect_url=add_url_params(
                reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:siaes_home")}
            ),
        )
        response = self.client.get(reverse("search:siaes_home"))
        self.assertContains(response, "existe déjà avec cette adresse e-mail")
        self.assertContains(response, "pour devenir employeur sur la plateforme")
        assert get_user(self.client).is_authenticated is False

        response = mock_oauth_dance(self.client, UserKind.EMPLOYER, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.PRESCRIBER
        assert get_user(self.client).is_authenticated is True

    @respx.mock
    def test_callback_refuses_job_seekers(self):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)
        user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=UserKind.JOB_SEEKER)

        expected_redirect_url = add_url_params(
            reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:siaes_home")}
        )

        mock_oauth_dance(self.client, UserKind.PRESCRIBER, expected_redirect_url=expected_redirect_url)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(self.client).is_authenticated is False

        mock_oauth_dance(self.client, UserKind.PRESCRIBER, expected_redirect_url=expected_redirect_url, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(self.client).is_authenticated is False

        mock_oauth_dance(self.client, UserKind.EMPLOYER, expected_redirect_url=expected_redirect_url)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(self.client).is_authenticated is False

        mock_oauth_dance(self.client, UserKind.EMPLOYER, expected_redirect_url=expected_redirect_url, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(self.client).is_authenticated is False

    @respx.mock
    def test_callback_redirect_prescriber_on_too_many_kind_exception(self):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        for kind in [UserKind.JOB_SEEKER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=kind)
            response = mock_oauth_dance(
                self.client,
                UserKind.PRESCRIBER,
                expected_redirect_url=add_url_params(
                    reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:siaes_home")}
                ),
            )
            response = self.client.get(reverse("search:siaes_home"))
            self.assertContains(response, "existe déjà avec cette adresse e-mail")
            self.assertContains(response, "pour devenir prescripteur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_redirect_employer_on_too_many_kind_exception(self):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)

        for kind in [UserKind.JOB_SEEKER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=kind)
            # Don't check redirection as the user isn't an siae member yet, so it won't work.
            response = mock_oauth_dance(
                self.client,
                UserKind.EMPLOYER,
                expected_redirect_url=add_url_params(
                    reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:siaes_home")}
                ),
            )
            response = self.client.get(reverse("search:siaes_home"))
            self.assertContains(response, "existe déjà avec cette adresse e-mail")
            self.assertContains(response, "pour devenir employeur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_updating_email_collision(self):
        PrescriberFactory(
            first_name="Bernard",
            last_name="Blier",
            username="bernard_blier",
            email=OIDC_USERINFO["email"],
            identity_provider=users_enums.IdentityProvider.DJANGO,
        )
        user = PrescriberFactory(
            first_name=OIDC_USERINFO["given_name"],
            last_name=OIDC_USERINFO["family_name"],
            username=OIDC_USERINFO["sub"],
            email="random@email.com",
            identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT,
        )
        self.client.force_login(user)
        edit_user_info_url = reverse("dashboard:edit_user_info")
        response = mock_oauth_dance(self.client, UserKind.PRESCRIBER, next_url=edit_user_info_url)
        response = self.client.get(response.url, follow=True)
        assertMessages(
            response,
            [
                (
                    messages.ERROR,
                    "Vous avez modifié votre e-mail sur Inclusion Connect, mais celui-ci est déjà associé à un compte "
                    "sur la plateforme. Nous n'avons donc pas pu mettre à jour random@email.com en "
                    f"{OIDC_USERINFO['email']}. Veuillez vous rapprocher du support pour débloquer la situation en "
                    f"suivant <a href='{ global_constants.ITOU_HELP_CENTER_URL }'>ce lien</a>.",
                )
            ],
        )


class InclusionConnectAccountActivationTest(InclusionConnectBaseTestCase):
    def test_new_user(self):
        params = {"user_email": OIDC_USERINFO["email"], "user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = self.client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_REGISTER)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in self.client.session
        assert f"login_hint={quote(OIDC_USERINFO['email'])}" in response.url

    def test_existing_django_user(self):
        user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        params = {"user_email": user.email, "user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = self.client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_ACTIVATE)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in self.client.session
        assert f"login_hint={quote(user.email)}" in response.url
        assert f"firstname={user.first_name}" in response.url
        assert f"lastname={user.last_name}" in response.url

    def test_existing_ic_user(self):
        user = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        params = {"user_email": user.email, "user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = self.client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in self.client.session
        assert f"login_hint={quote(user.email)}" in response.url

    def test_bad_user_kind(self):
        for user in [JobSeekerFactory(), PrescriberFactory(), EmployerFactory(), LaborInspectorFactory()]:
            user_kind = UserKind.PRESCRIBER if user.kind != UserKind.PRESCRIBER else UserKind.EMPLOYER
            with self.subTest(user_kind=user_kind):
                params = {"user_email": user.email, "user_kind": user_kind}
                url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
                response = self.client.get(url, follow=True)
                self.assertRedirects(response, reverse("search:siaes_home"))
                self.assertContains(response, "existe déjà avec cette adresse e-mail")
                self.assertContains(
                    response, "Vous devez créer un compte Inclusion Connect avec une autre adresse e-mail"
                )

    def test_no_email(self):
        params = {"user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = self.client.get(url)
        self.assertRedirects(response, reverse("search:siaes_home"))


class InclusionConnectSessionTest(InclusionConnectBaseTestCase):
    def test_start_session(self):
        ic_session = InclusionConnectSession()
        assert ic_session.key == constants.INCLUSION_CONNECT_SESSION_KEY

        expected_keys = ["token", "state"]
        ic_session_dict = ic_session.asdict()
        for key in expected_keys:
            with self.subTest(key):
                assert key in ic_session_dict.keys()
                assert ic_session_dict[key] is None

        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()
        ic_session.bind_to_request(request)
        assert request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)


class InclusionConnectLoginTest(InclusionConnectBaseTestCase):
    @respx.mock
    def test_normal_signin(self):
        """
        A user has created an account with Inclusion Connect.
        He logs out.
        He can log in again later.
        """
        # Create an account with IC.
        response = mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        self.client.get(response.url)  # display welcoming_tour

        # Then log out.
        response = self.client.post(reverse("account_logout"))

        # Then log in again.
        login_url = reverse("login:prescriber")
        response = self.client.get(login_url)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")
        self.assertContains(response, reverse("inclusion_connect:authorize"))

        response = mock_oauth_dance(self.client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))

        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=OIDC_USERINFO["email"]).count()
        assert users_count == 1

    @respx.mock
    def test_old_django_account(self):
        """
        A user has a Django account.
        He clicks on IC button and creates his account.
        His old Django account should now be considered as an IC one.
        """
        user_info = OIDC_USERINFO
        user = PrescriberFactory(
            has_completed_welcoming_tour=True,
            **InclusionConnectPrescriberData.user_info_mapping_dict(user_info),
            identity_provider=IdentityProvider.DJANGO,
        )

        # Existing user connects with IC which results in:
        # - IC side: account creation
        # - Django side: account update.
        # This logic is already tested here: InclusionConnectModelTest
        response = mock_oauth_dance(self.client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))
        assert auth.get_user(self.client).is_authenticated
        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=OIDC_USERINFO["email"]).count()
        assert users_count == 1

        response = self.client.post(reverse("account_logout"))
        assert response.status_code == 302
        assert not auth.get_user(self.client).is_authenticated

        # Try to login with Django.
        # This is already tested in itou.www.login.tests but only at form level.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(reverse("login:prescriber"), data=post_data)
        error_message = "Votre compte est relié à Inclusion Connect."
        self.assertContains(response, error_message)
        assert not auth.get_user(self.client).is_authenticated

        # Then login with Inclusion Connect.
        mock_oauth_dance(self.client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))
        assert auth.get_user(self.client).is_authenticated


class InclusionConnectLogoutTest(InclusionConnectBaseTestCase):
    @respx.mock
    def test_simple_logout(self):
        mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        logout_url = reverse("inclusion_connect:logout")
        response = self.client.get(logout_url)
        self.assertRedirects(
            response,
            add_url_params(
                constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT,
                {"id_token_hint": 123456, "post_logout_redirect_uri": get_absolute_url(reverse("search:siaes_home"))},
            ),
            fetch_redirect_response=False,
        )

    @respx.mock
    def test_logout_with_redirection(self):
        mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        expected_redirection = reverse("dashboard:index")

        params = {"redirect_url": expected_redirection}
        logout_url = f"{reverse('inclusion_connect:logout')}?{urlencode(params)}"
        response = self.client.get(logout_url)
        self.assertRedirects(
            response,
            add_url_params(
                constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT,
                {"id_token_hint": 123456, "post_logout_redirect_uri": get_absolute_url(expected_redirection)},
            ),
            fetch_redirect_response=False,
        )

    @respx.mock
    def test_django_account_logout_from_ic(self):
        """
        When ac IC user wants to log out from his local account,
        he should be logged out too from IC.
        """
        response = mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        assert auth.get_user(self.client).is_authenticated
        # Follow the redirection.
        response = self.client.get(response.url)
        logout_url = reverse("account_logout")
        self.assertContains(response, logout_url)
        assert self.client.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)

        response = self.client.post(logout_url)
        expected_redirection = reverse("inclusion_connect:logout")
        # For simplicity, exclude GET params. They are tested elsewhere anyway..
        assert response.url.startswith(expected_redirection)

        response = self.client.get(response.url)
        # The following redirection is tested in self.test_logout_with_redirection
        assert response.status_code == 302
        assert not auth.get_user(self.client).is_authenticated

    def test_django_account_logout(self):
        """
        When a local user wants to log out from his local account,
        he should be logged out without inclusion connect.
        """
        user = PrescriberFactory()
        self.client.force_login(user)
        response = self.client.post(reverse("account_logout"))
        self.assertRedirects(response, reverse("search:siaes_home"))
        assert not auth.get_user(self.client).is_authenticated

    @respx.mock
    def test_logout_with_incomplete_state(self):
        # This happens while testing. It should never happen for real users, but it's still painful for us.

        mock_oauth_dance(self.client, UserKind.PRESCRIBER)
        respx.get(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(200)

        session = self.client.session
        session[constants.INCLUSION_CONNECT_SESSION_KEY]["token"] = None
        session[constants.INCLUSION_CONNECT_SESSION_KEY]["state"] = None
        session.save()

        response = self.client.post(reverse("account_logout"))
        self.assertRedirects(response, reverse("search:siaes_home"))
