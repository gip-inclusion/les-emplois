import dataclasses
import json
import random
from operator import itemgetter
from unittest import mock
from urllib.parse import quote, urlencode

import httpx
import pytest
import respx
from django.contrib import auth, messages
from django.contrib.auth import get_user
from django.contrib.messages import Message
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertQuerySetEqual,
    assertRedirects,
)

from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.openid_connect.models import InvalidKindException
from itou.openid_connect.pro_connect import constants
from itou.openid_connect.pro_connect.enums import ProConnectChannel
from itou.openid_connect.pro_connect.models import (
    ProConnectEmployerData,
    ProConnectPrescriberData,
    ProConnectState,
)
from itou.openid_connect.pro_connect.views import ProConnectSession
from itou.prescribers.models import PrescriberOrganization
from itou.users import enums as users_enums
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.urls import add_url_params, get_absolute_url
from tests.job_applications.factories import JobApplicationSentByPrescriberPoleEmploiFactory
from tests.prescribers.factories import PrescriberPoleEmploiFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    PrescriberFactory,
    UserFactory,
)


class TestProConnectModel:
    def test_state_delete(self):
        state = ProConnectState.objects.create(state="foo")

        ProConnectState.objects.cleanup()

        state.refresh_from_db()
        assert state is not None

        # Set creation time for the state so that the state is expired
        state.created_at = timezone.now() - OIDC_STATE_CLEANUP * 2
        state.save()

        ProConnectState.objects.cleanup()

        with pytest.raises(ProConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_is_valid(self):
        with freeze_time("2022-09-13 12:00:01"):
            state = ProConnectState.save_state()
            assert isinstance(state, str)
            assert ProConnectState.get_from_state(state).is_valid()

            state = ProConnectState.save_state()
        with freeze_time("2022-10-13 12:00:01"):
            assert not ProConnectState.get_from_state(state).is_valid()

    def test_create_user_from_user_info(self, pro_connect):
        """
        Nominal scenario: there is no user with the ProConnect ID or ProConnect email
        that is sent, so we create one.
        Similar to france_connect.tests.FranceConnectTest.test_create_django_user
        but with more tests.
        """
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        assert not User.objects.filter(username=pc_user_data.username).exists()
        assert not User.objects.filter(email=pc_user_data.email).exists()

        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            user, created = pc_user_data.create_or_update_user()
        assert created
        assert user.email == pro_connect.oidc_userinfo["email"]
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.username == pro_connect.oidc_userinfo["sub"]

        user.refresh_from_db()
        expected = [
            {
                "field_name": field.name,
                "value": getattr(user, field.name),
                "source": "PC",
                "created_at": now_str,
            }
            for field in dataclasses.fields(pc_user_data)
        ]
        assert sorted(user.external_data_source_history, key=itemgetter("field_name")) == sorted(
            expected, key=itemgetter("field_name")
        )

    def test_create_user_from_user_info_with_already_existing_id(self, pro_connect):
        """
        If there already is an existing user with this ProConnect id, we do not create it again,
        we use it and we update it.
        """
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        PrescriberFactory(
            username=pc_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.PRO_CONNECT,
        )
        user, created = pc_user_data.create_or_update_user()
        assert not created
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.external_data_source_history[0]["source"] == "PC"

    def test_create_user_from_user_info_with_already_existing_id_but_from_other_sso(self, pro_connect):
        """
        If there already is an existing user with this ProConnect id, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        PrescriberFactory(
            username=pc_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.DJANGO,
            email="random@email.com",
        )
        with pytest.raises(ValidationError):
            pc_user_data.create_or_update_user()

    def test_create_user_from_user_info_with_already_existing_email_but_other_sub(self, pro_connect):
        """
        If there already is an existing user with this email but another ProConnect sub,
        allow login and update the sub.
        """
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        PrescriberFactory(
            username="another_sub",
            identity_provider=users_enums.IdentityProvider.PRO_CONNECT,
            email=pc_user_data.email,
        )
        user, created = pc_user_data.create_or_update_user()
        assert not created
        assert user.username == pro_connect.oidc_userinfo["sub"]
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.external_data_source_history[0]["source"] == "PC"

    def test_join_org(self, caplog, pro_connect):
        # New membership.
        organization = PrescriberPoleEmploiFactory()
        assert organization.active_members.count() == 0
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        user, _ = pc_user_data.create_or_update_user()
        pc_user_data.join_org(user=user, safir=organization.code_safir_pole_emploi)

        assert organization.active_members.count() == 1
        assert organization.has_admin(user)

        # User is already a member.
        pc_user_data.join_org(user=user, safir=organization.code_safir_pole_emploi)
        assert organization.active_members.count() == 1
        assert organization.has_admin(user)

        # Oganization does not exist.
        safir = "12345"
        with pytest.raises(PrescriberOrganization.DoesNotExist):
            pc_user_data.join_org(user=user, safir=safir)

        assert f"Organization with SAFIR {safir} does not exist. Unable to add user {user}." in caplog.messages
        assert organization.active_members.count() == 1
        assert organization.has_admin(user)

    def test_get_existing_user_with_same_email_django(self, pro_connect):
        """
        If there already is an existing django user with email ProConnect sent us, we do not create it again,
        We user it and we update it with the data form the identity_provider.
        """
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        PrescriberFactory(email=pc_user_data.email, identity_provider=users_enums.IdentityProvider.DJANGO)
        user, created = pc_user_data.create_or_update_user()
        assert not created
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.username == pro_connect.oidc_userinfo["sub"]
        assert user.identity_provider == users_enums.IdentityProvider.PRO_CONNECT

    def test_get_existing_user_with_same_email_IC(self, pro_connect):
        """
        If there already is an existing IC user with email ProConnect sent us, we do not create it again,
        We user it and we update it with the data form the identity_provider.
        """
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        PrescriberFactory(email=pc_user_data.email, identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT)
        user, created = pc_user_data.create_or_update_user()
        assert not created
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.username == pro_connect.oidc_userinfo["sub"]
        assert user.identity_provider == users_enums.IdentityProvider.PRO_CONNECT

    def test_update_user_from_user_info(self, pro_connect):
        user = PrescriberFactory(
            **dataclasses.asdict(ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo))
        )
        pc_user = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)

        new_pc_user = ProConnectPrescriberData(
            first_name="Jean", last_name="Gabin", username=pc_user.username, email="jean@lestontons.fr"
        )
        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            user, created = new_pc_user.create_or_update_user()
        assert not created

        user.refresh_from_db()
        expected = [
            {
                "field_name": field.name,
                "value": getattr(user, field.name),
                "source": "PC",
                "created_at": now_str,
            }
            for field in dataclasses.fields(pc_user)
        ]
        assert sorted(user.external_data_source_history, key=itemgetter("field_name")) == sorted(
            expected, key=itemgetter("field_name")
        )

    def test_create_or_update_prescriber_raise_too_many_kind_exception(self, pro_connect):
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)

        for kind in [UserKind.JOB_SEEKER, UserKind.EMPLOYER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=kind)

            with pytest.raises(InvalidKindException):
                pc_user_data.create_or_update_user()

            user.delete()

    def test_create_or_update_employer_raise_too_many_kind_exception(self, pro_connect):
        pc_user_data = ProConnectEmployerData.from_user_info(pro_connect.oidc_userinfo)

        for kind in [UserKind.JOB_SEEKER, UserKind.PRESCRIBER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=kind)

            with pytest.raises(InvalidKindException):
                pc_user_data.create_or_update_user()

            user.delete()


class TestProConnectAuthorizeView:
    def test_authorize_endpoint(self, client, pro_connect):
        url = reverse("pro_connect:authorize")
        response = client.get(url, follow=False)
        assertRedirects(response, reverse("search:employers_home"))

        url = f"{pro_connect.authorize_url}?user_kind={UserKind.PRESCRIBER}"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.PRO_CONNECT_ENDPOINT_AUTHORIZE)
        pc_state = ProConnectState.get_from_state(client.session[constants.PRO_CONNECT_SESSION_KEY]["state"])
        assert pc_state.nonce is not None
        assert f"nonce={pc_state.nonce}" in response.url

    def test_authorize_endpoint_for_registration(self, client, pro_connect):
        url = reverse("pro_connect:authorize")
        response = client.get(url, follow=False)
        assertRedirects(response, reverse("search:employers_home"))

        url = f"{pro_connect.authorize_url}?user_kind={UserKind.PRESCRIBER}&register=true"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.PRO_CONNECT_ENDPOINT_AUTHORIZE)
        pc_state = ProConnectState.get_from_state(client.session[constants.PRO_CONNECT_SESSION_KEY]["state"])
        assert pc_state.nonce is not None
        assert f"nonce={pc_state.nonce}" in response.url

    def test_authorize_endpoint_with_params(self, client, pro_connect):
        email = "porthos@touspourun.com"
        params = {"user_email": email, "user_kind": UserKind.PRESCRIBER, "channel": "invitation"}
        url = f"{pro_connect.authorize_url}?{urlencode(params)}"
        response = client.get(url, follow=False)
        assert f"login_hint={quote(email)}" in response.url
        pc_state = ProConnectState.get_from_state(client.session[constants.PRO_CONNECT_SESSION_KEY]["state"])
        assert pc_state.data["user_email"] == email
        assert pc_state.nonce is not None
        assert f"nonce={pc_state.nonce}" in response.url

    def test_authorize_check_user_kind(self, client, pro_connect, subtests):
        forbidden_user_kinds = [UserKind.ITOU_STAFF, UserKind.LABOR_INSPECTOR, UserKind.JOB_SEEKER]
        for kind in forbidden_user_kinds:
            with subtests.test(kind=kind.label):
                url = f"{pro_connect.authorize_url}?user_kind={kind}"
                response = client.get(url)
                assertRedirects(response, reverse("search:employers_home"))

    def test_next_url(self, client, pro_connect, caplog):
        url = f"{pro_connect.authorize_url}?{urlencode({'next_url': 'https://external.url.com'})}"
        response = client.get(url, follow=False)
        assertRedirects(response, reverse("search:employers_home"))
        assert caplog.records[0].message == "Forbidden external url"


class TestProConnectCallbackView:
    @respx.mock
    def test_callback_invalid_state(self, client, pro_connect):
        token_json = {"access_token": "access_token", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
        respx.post(constants.PRO_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

        url = reverse("pro_connect:callback")
        response = client.get(url, data={"code": "123", "state": "000"})
        assert response.status_code == 302

    def test_callback_no_state(self, client):
        url = reverse("pro_connect:callback")
        response = client.get(url, data={"code": "123"})
        assert response.status_code == 302

    def test_callback_no_code(self, client):
        url = reverse("pro_connect:callback")
        response = client.get(url)
        assert response.status_code == 302

    @respx.mock
    def test_callback_prescriber_created(self, client, pro_connect):
        ### User does not exist.
        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.username == pro_connect.oidc_userinfo["sub"]
        assert user.has_sso_provider
        assert user.kind == "prescriber"
        assert user.identity_provider == users_enums.IdentityProvider.PRO_CONNECT

    @respx.mock
    def test_callback_employer_created(self, client, pro_connect):
        ### User does not exist.
        pro_connect.mock_oauth_dance(client, UserKind.EMPLOYER)
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.username == pro_connect.oidc_userinfo["sub"]
        assert user.has_sso_provider
        assert user.kind == UserKind.EMPLOYER
        assert user.identity_provider == users_enums.IdentityProvider.PRO_CONNECT

    @respx.mock
    def test_callback_existing_django_user(self, client, pro_connect):
        # User created with django already exists on Itou but some attributes differs.
        # Update all fields
        PrescriberFactory(
            first_name="Bernard",
            last_name="Blier",
            username="bernard_blier",
            email=pro_connect.oidc_userinfo["email"],
            identity_provider=users_enums.IdentityProvider.DJANGO,
        )
        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.first_name == pro_connect.oidc_userinfo["given_name"]
        assert user.last_name == pro_connect.oidc_userinfo["usual_name"]
        assert user.username == pro_connect.oidc_userinfo["sub"]
        assert user.has_sso_provider
        assert user.identity_provider == users_enums.IdentityProvider.PRO_CONNECT

    @respx.mock
    def test_callback_allows_employer_on_prescriber_login_only(self, client, pro_connect):
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=UserKind.EMPLOYER)

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            expected_redirect_url=reverse(
                "pro_connect:logout", query={"redirect_url": reverse("search:employers_home")}
            ),
        )
        response = client.get(reverse("search:employers_home"))
        assertContains(response, "existe déjà avec cette adresse e-mail")
        assertContains(response, "pour devenir prescripteur sur la plateforme")
        assert get_user(client).is_authenticated is False

        response = pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.EMPLOYER
        assert get_user(client).is_authenticated is True

    @respx.mock
    def test_callback_allows_prescriber_on_employer_login_only(self, client, pro_connect):
        pc_user_data = ProConnectEmployerData.from_user_info(pro_connect.oidc_userinfo)
        user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=UserKind.PRESCRIBER)

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            expected_redirect_url=reverse(
                "pro_connect:logout", query={"redirect_url": reverse("search:employers_home")}
            ),
        )
        response = client.get(reverse("search:employers_home"))
        assertContains(response, "existe déjà avec cette adresse e-mail")
        assertContains(response, "pour devenir employeur sur la plateforme")
        assert get_user(client).is_authenticated is False

        response = pro_connect.mock_oauth_dance(client, UserKind.EMPLOYER, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.PRESCRIBER
        assert get_user(client).is_authenticated is True

    @respx.mock
    def test_callback_refuses_job_seekers(self, client, pro_connect):
        pc_user_data = ProConnectEmployerData.from_user_info(pro_connect.oidc_userinfo)
        user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=UserKind.JOB_SEEKER)

        expected_redirect_url = reverse("pro_connect:logout", query={"redirect_url": reverse("search:employers_home")})

        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=expected_redirect_url)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

        pro_connect.mock_oauth_dance(
            client, UserKind.PRESCRIBER, expected_redirect_url=expected_redirect_url, register=False
        )
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

        pro_connect.mock_oauth_dance(client, UserKind.EMPLOYER, expected_redirect_url=expected_redirect_url)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

        pro_connect.mock_oauth_dance(
            client, UserKind.EMPLOYER, expected_redirect_url=expected_redirect_url, register=False
        )
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

    @respx.mock
    def test_callback_redirect_prescriber_on_too_many_kind_exception(self, client, pro_connect):
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)

        for kind in [UserKind.JOB_SEEKER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=kind)
            response = pro_connect.mock_oauth_dance(
                client,
                UserKind.PRESCRIBER,
                expected_redirect_url=reverse(
                    "pro_connect:logout", query={"redirect_url": reverse("search:employers_home")}
                ),
            )
            response = client.get(reverse("search:employers_home"))
            assertContains(response, "existe déjà avec cette adresse e-mail")
            assertContains(response, "pour devenir prescripteur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_redirect_on_inactive_user_exception(self, client, pro_connect):
        pc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)

        user = UserFactory(
            username=pc_user_data.username,
            email=pc_user_data.email,
            kind=random.choice([UserKind.EMPLOYER, UserKind.PRESCRIBER]),
            is_active=False,
        )
        response = pro_connect.mock_oauth_dance(
            client,
            user.kind,
            expected_redirect_url=reverse(
                "pro_connect:logout", query={"redirect_url": reverse("search:employers_home")}
            ),
        )
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La connexion via ProConnect a fonctionné mais le compte lié sur les Emplois de l’inclusion "
                        "est désactivé. Veuillez vous rapprocher du support pour débloquer la situation en suivant "
                        '<a href="https://aide.emplois.inclusion.beta.gouv.fr/hc/fr">ce lien</a>.'
                    ),
                )
            ],
        )

    @respx.mock
    def test_callback_redirect_employer_on_too_many_kind_exception(self, client, pro_connect):
        pc_user_data = ProConnectEmployerData.from_user_info(pro_connect.oidc_userinfo)

        for kind in [UserKind.JOB_SEEKER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=pc_user_data.username, email=pc_user_data.email, kind=kind)
            # Don't check redirection as the user isn't an siae member yet, so it won't work.
            response = pro_connect.mock_oauth_dance(
                client,
                UserKind.EMPLOYER,
                expected_redirect_url=reverse(
                    "pro_connect:logout", query={"redirect_url": reverse("search:employers_home")}
                ),
            )
            response = client.get(reverse("search:employers_home"))
            assertContains(response, "existe déjà avec cette adresse e-mail")
            assertContains(response, "pour devenir employeur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_update_sub_on_sub_conflict(self, client, pro_connect):
        oidc_user_data = ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)
        user = PrescriberFactory(
            username="another_sub", email=oidc_user_data.email, identity_provider=IdentityProvider.PRO_CONNECT
        )

        pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
        )
        user.refresh_from_db()
        assert user.username == pro_connect.oidc_userinfo["sub"]

    @respx.mock
    def test_callback_updating_email_collision(self, client, pro_connect):
        PrescriberFactory(
            first_name="Bernard",
            last_name="Blier",
            username="bernard_blier",
            email=pro_connect.oidc_userinfo["email"],
            identity_provider=users_enums.IdentityProvider.DJANGO,
        )
        user = PrescriberFactory(
            first_name=pro_connect.oidc_userinfo["given_name"],
            last_name=pro_connect.oidc_userinfo["usual_name"],
            username=pro_connect.oidc_userinfo["sub"],
            email="random@email.com",
            identity_provider=users_enums.IdentityProvider.PRO_CONNECT,
        )
        client.force_login(user)
        edit_user_info_url = reverse("dashboard:edit_user_info")
        response = pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER, next_url=edit_user_info_url)
        response = client.get(response.url, follow=True)
        assertMessages(
            response,
            [
                Message(
                    messages.ERROR,
                    "L'adresse e-mail que nous a transmis ProConnect est différente de celle qui est enregistrée "
                    "sur la plateforme des emplois, et est déjà associé à un autre compte. "
                    "Nous n'avons donc pas pu mettre à jour random@email.com en "
                    f"{pro_connect.oidc_userinfo['email']}. Veuillez vous rapprocher du support pour débloquer la "
                    f"situation en suivant <a href='{global_constants.ITOU_HELP_CENTER_URL}'>ce lien</a>.",
                )
            ],
        )

    @respx.mock
    def test_callback_update_FT_organization(self, client, pro_connect):
        user = PrescriberFactory(
            **dataclasses.asdict(ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo))
        )
        org = PrescriberPoleEmploiFactory(code_safir_pole_emploi="95021")
        assert not org.members.exists()

        pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=pro_connect.oidc_userinfo_with_safir.copy(),
        )
        assertQuerySetEqual(org.members.all(), [user])

    @respx.mock
    def test_callback_update_FT_organization_as_employer_does_not_crash(self, client, pro_connect):
        org = PrescriberPoleEmploiFactory(code_safir_pole_emploi="95021")
        pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            oidc_userinfo=pro_connect.oidc_userinfo_with_safir.copy(),
        )
        user = get_user(client)
        assert user.is_authenticated
        assert not user.prescribermembership_set.exists()

        # If he's a prescriber and uses the employer login button
        user.kind = UserKind.PRESCRIBER
        user.save()
        client.logout()
        pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            oidc_userinfo=pro_connect.oidc_userinfo_with_safir.copy(),
            register=False,
        )
        user = get_user(client)
        assert user.is_authenticated
        assertQuerySetEqual(org.members.all(), [user])

    @respx.mock
    def test_callback_ft_users_with_no_org(self, client, pro_connect):
        PrescriberFactory(**dataclasses.asdict(ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)))

        oidc_userinfo = pro_connect.oidc_userinfo.copy()
        oidc_userinfo["email"] = "prenom.nom@francetravail.fr"
        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=oidc_userinfo,
        )
        # fetch post login page to trigger perm middleware
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "ft_no_ft_organization"}))

        response = client.post(reverse("account_logout"))
        pro_connect.assert_and_mock_forced_logout(client, response)
        assert get_user(client).is_authenticated is False

    @respx.mock
    def test_callback_ft_users_unknown_safir(self, client, pro_connect):
        PrescriberFactory(**dataclasses.asdict(ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo)))

        oidc_userinfo = pro_connect.oidc_userinfo_with_safir.copy()
        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=oidc_userinfo,
        )
        # fetch post login page to trigger perm middleware
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "ft_no_ft_organization"}))
        assertMessages(
            response,
            [
                Message(
                    messages.WARNING,
                    "L'agence indiquée par NEPTUNE (code SAFIR 95021) n'est pas référencée dans notre service. "
                    "Cela arrive quand vous appartenez à un Point Relais mais que vous êtes rattaché à une agence "
                    "mère sur la plateforme des emplois. "
                    "Si vous pensez qu'il y a une erreur, vérifiez que le code SAFIR est le bon "
                    f"puis <a href='{global_constants.ITOU_HELP_CENTER_URL}'>contactez le support</a> en indiquant "
                    "le code SAFIR.",
                ),
            ],
        )

        response = client.post(reverse("account_logout"))
        pro_connect.assert_and_mock_forced_logout(client, response)
        assert get_user(client).is_authenticated is False

    @respx.mock
    def test_callback_ft_users_unknown_safir_already_in_org(self, client, pro_connect):
        user = PrescriberFactory(
            **dataclasses.asdict(ProConnectPrescriberData.from_user_info(pro_connect.oidc_userinfo))
        )
        org = PrescriberPoleEmploiFactory(code_safir_pole_emploi="00000")
        org.add_or_activate_membership(user)

        oidc_userinfo = pro_connect.oidc_userinfo_with_safir.copy()
        oidc_userinfo["email"] = "prenom.nom@francetravail.fr"
        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=oidc_userinfo,
        )
        assert get_user(client).is_authenticated is True
        assertMessages(
            response,
            [
                Message(
                    messages.WARNING,
                    "L'agence indiquée par NEPTUNE (code SAFIR 95021) n'est pas référencée dans notre service. "
                    "Cela arrive quand vous appartenez à un Point Relais mais que vous êtes rattaché à une agence "
                    "mère sur la plateforme des emplois. "
                    "Si vous pensez qu'il y a une erreur, vérifiez que le code SAFIR est le bon "
                    f"puis <a href='{global_constants.ITOU_HELP_CENTER_URL}'>contactez le support</a> en indiquant "
                    "le code SAFIR.",
                )
            ],
        )


class TestProConnectSession:
    def test_start_session(self, subtests):
        pc_session = ProConnectSession()
        assert pc_session.key == constants.PRO_CONNECT_SESSION_KEY

        expected_keys = ["token", "state"]
        pc_session_dict = dataclasses.asdict(pc_session)
        for key in expected_keys:
            with subtests.test(key):
                assert key in pc_session_dict.keys()
                assert pc_session_dict[key] is None

        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()
        pc_session.bind_to_request(request)
        assert request.session.get(constants.PRO_CONNECT_SESSION_KEY)


class TestProConnectLogin:
    @respx.mock
    def test_normal_signin(self, client, pro_connect):
        """
        A user has created an account with ProConnect.
        He logs out.
        He can log in again later.
        """
        # Create an account with ProConnect.
        response = pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)
        client.get(response.url)  # display welcoming_tour

        # Then log out.
        response = client.post(reverse("account_logout"))
        pro_connect.assert_and_mock_forced_logout(client, response)

        # Then log in again.
        login_url = reverse("login:prescriber")
        response = client.get(login_url)
        assertContains(response, 'class="proconnect-button"')
        assertContains(response, reverse("pro_connect:authorize"))

        before_auth = timezone.now()
        response = pro_connect.mock_oauth_dance(
            client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index")
        )

        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.last_login > before_auth

    @respx.mock
    def test_old_django_account(self, client, pro_connect, settings):
        """
        A user has a Django account.
        He clicks on ProConnect button and creates his account.
        His old Django account should now be considered as an ProConnect one.
        """
        user_info = pro_connect.oidc_userinfo
        user = PrescriberFactory(
            has_completed_welcoming_tour=True,
            **ProConnectPrescriberData.user_info_mapping_dict(user_info),
            identity_provider=IdentityProvider.DJANGO,
            with_verified_email=True,
        )

        # Existing user connects with Proconnect which results in:
        # - ProConnect side: account creation
        # - Django side: account update.
        # This logic is already tested here: ProConnectModelTest
        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))
        assert auth.get_user(client).is_authenticated
        user.refresh_from_db()
        assert user.identity_provider == IdentityProvider.PRO_CONNECT

        response = client.post(reverse("account_logout"))
        pro_connect.assert_and_mock_forced_logout(client, response)
        assert not auth.get_user(client).is_authenticated

        # Try to login with Django.
        # This is already tested in itou.www.login.tests but only at form level.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        response = client.post(reverse("login:prescriber"), data=post_data)
        error_message = "Votre compte est relié à ProConnect."
        assertContains(response, error_message)
        assert not auth.get_user(client).is_authenticated

        # But it's possible if we allow it
        settings.FORCE_PROCONNECT_LOGIN = False
        response = client.post(reverse("login:prescriber"), data=post_data)
        assertRedirects(response, reverse("dashboard:index"))
        assert auth.get_user(client).is_authenticated


class TestProConnectLogout:
    @respx.mock
    def test_simple_logout(self, client, pro_connect):
        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)
        logout_url = reverse("pro_connect:logout")
        response = client.get(logout_url)
        post_logout_redirect_uri = get_absolute_url(reverse("pro_connect:logout_callback"))
        state = ProConnectState.objects.get(used_at=None).state
        signed_state = signing.Signer().sign(state)

        assertRedirects(
            response,
            add_url_params(
                constants.PRO_CONNECT_ENDPOINT_LOGOUT,
                {
                    "id_token_hint": 123456,
                    "state": signed_state,
                    "post_logout_redirect_uri": post_logout_redirect_uri,
                },
            ),
            fetch_redirect_response=False,
        )
        response = client.get(post_logout_redirect_uri)
        assertRedirects(response, reverse("search:employers_home"))

    @respx.mock
    def test_logout_with_redirection(self, client, pro_connect):
        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)
        expected_redirection = reverse("dashboard:index")

        params = {"redirect_url": expected_redirection}
        logout_url = f"{reverse('pro_connect:logout')}?{urlencode(params)}"
        response = client.get(logout_url)
        post_logout_redirect_uri = get_absolute_url(reverse("pro_connect:logout_callback"))
        state = ProConnectState.objects.get(used_at=None).state
        signed_state = signing.Signer().sign(state)

        assertRedirects(
            response,
            add_url_params(
                constants.PRO_CONNECT_ENDPOINT_LOGOUT,
                {
                    "id_token_hint": 123456,
                    "state": signed_state,
                    "post_logout_redirect_uri": post_logout_redirect_uri,
                },
            ),
            fetch_redirect_response=False,
        )
        response = client.get(add_url_params(post_logout_redirect_uri, {"state": signed_state}))
        assertRedirects(response, expected_redirection)

    @respx.mock
    def test_django_account_logout_from_pro(self, client, pro_connect):
        """
        When ac ProConnect user wants to log out from his local account,
        he should be logged out too from ProConnect.
        """
        response = pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)
        assert auth.get_user(client).is_authenticated
        # Follow the redirection.
        response = client.get(response.url)
        logout_url = reverse("account_logout")
        assertContains(response, logout_url)
        assert client.session.get(constants.PRO_CONNECT_SESSION_KEY)

        response = client.post(logout_url)
        pro_connect.assert_and_mock_forced_logout(client, response)
        assert not auth.get_user(client).is_authenticated

    def test_django_account_logout(self, client):
        """
        When a local user wants to log out from his local account,
        he should be logged out without pro connect.
        """
        user = PrescriberFactory()
        client.force_login(user)
        response = client.post(reverse("account_logout"))
        assertRedirects(response, reverse("search:employers_home"))
        assert not auth.get_user(client).is_authenticated

    @respx.mock
    def test_logout_with_incomplete_state(self, client, pro_connect):
        # This happens while testing. It should never happen for real users, but it's still painful for us.

        pro_connect.mock_oauth_dance(client, UserKind.PRESCRIBER)

        session = client.session
        session[constants.PRO_CONNECT_SESSION_KEY]["token"] = None
        session[constants.PRO_CONNECT_SESSION_KEY]["state"] = None
        session.save()

        response = client.post(reverse("account_logout"))
        assertRedirects(response, reverse("search:employers_home"))
        assert not auth.get_user(client).is_authenticated


class TestProConnectMapChannel:
    @respx.mock
    def test_happy_path(self, client, pro_connect):
        job_application = JobApplicationSentByPrescriberPoleEmploiFactory(
            sender_prescriber_organization__code_safir_pole_emploi="95021"
        )
        prescriber = job_application.sender
        prescriber.email = pro_connect.oidc_userinfo["email"]
        prescriber.username = pro_connect.oidc_userinfo["sub"]
        prescriber.save()
        url_from_map = "{path}?channel={channel}".format(
            path=reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            channel=ProConnectChannel.MAP_CONSEILLER.value,
        )

        response = client.get(url_from_map, follow=True)
        # Starting point of both the oauth_dance and `pro_connect.mock_oauth_dance()`.
        pc_endpoint = response.redirect_chain[-1][0]
        assert pc_endpoint.startswith(constants.PRO_CONNECT_ENDPOINT_AUTHORIZE)
        assert f"idp_hint={constants.PRO_CONNECT_FT_IDP_HINT}" in pc_endpoint

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            next_url=url_from_map,
            expected_redirect_url=url_from_map,
            channel=ProConnectChannel.MAP_CONSEILLER,
        )
        assert auth.get_user(client).is_authenticated

        response = client.get(response.url)
        assert response.status_code == 200

    @respx.mock
    def test_create_user(self, client, pro_connect):
        # Application sent by a colleague from the same agency but not by the prescriber himself.
        job_application = JobApplicationSentByPrescriberPoleEmploiFactory(
            sender_prescriber_organization__code_safir_pole_emploi="95021"
        )

        # Prescriber does not belong to this organization on Itou but
        # ProConnect says that he is allowed to join it.
        # A new user should be created automatically, only when coming from MAP conseiller,
        # and then be able to see a job application details.
        url_from_map = "{path}?channel={channel}".format(
            path=reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            channel=ProConnectChannel.MAP_CONSEILLER.value,
        )

        response = client.get(url_from_map, follow=True)
        # Starting point of both the oauth_dance and `pro_connect.mock_oauth_dance()`.
        pc_endpoint = response.redirect_chain[-1][0]
        assert pc_endpoint.startswith(constants.PRO_CONNECT_ENDPOINT_AUTHORIZE)

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            next_url=url_from_map,
            expected_redirect_url=url_from_map,
            channel=ProConnectChannel.MAP_CONSEILLER,
            oidc_userinfo=pro_connect.oidc_userinfo_with_safir.copy(),
        )
        assert job_application.sender_prescriber_organization.members.count() == 2
        assert auth.get_user(client).is_authenticated

        response = client.get(response.url)
        assert response.status_code == 200

    @respx.mock
    def test_create_user_organization_not_found(self, client, pro_connect):
        # Application sent by a colleague from the same agency but not by the prescriber himself.
        job_application = JobApplicationSentByPrescriberPoleEmploiFactory(
            sender_prescriber_organization__code_safir_pole_emploi=11111
        )

        # Prescriber does not belong to this organization on Itou but
        # ProConnect says that he is allowed to join it.
        # A new user should be created automatically and redirected to the job application details page.
        url_from_map = "{path}?channel={channel}".format(
            path=reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            channel=ProConnectChannel.MAP_CONSEILLER.value,
        )

        response = client.get(url_from_map, follow=True)
        # Starting point of both the oauth_dance and `pro_connect.mock_oauth_dance()`.
        pc_endpoint = response.redirect_chain[-1][0]
        assert pc_endpoint.startswith(constants.PRO_CONNECT_ENDPOINT_AUTHORIZE)

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            next_url=url_from_map,
            channel=ProConnectChannel.MAP_CONSEILLER,
            oidc_userinfo=pro_connect.oidc_userinfo_with_safir.copy(),
        )
        assert job_application.sender_prescriber_organization.members.count() == 1

        # fetch post login page to trigger perm middleware
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "ft_no_ft_organization"}))
        assertMessages(
            response,
            [
                Message(
                    messages.WARNING,
                    "L'agence indiquée par NEPTUNE (code SAFIR 95021) n'est pas référencée dans notre service. "
                    "Cela arrive quand vous appartenez à un Point Relais mais que vous êtes rattaché à une agence "
                    "mère sur la plateforme des emplois. "
                    "Si vous pensez qu'il y a une erreur, vérifiez que le code SAFIR est le bon "
                    f"puis <a href='{global_constants.ITOU_HELP_CENTER_URL}'>contactez le support</a> en indiquant "
                    "le code SAFIR.",
                ),
            ],
        )

        response = client.post(reverse("account_logout"))
        pro_connect.assert_and_mock_forced_logout(client, response)
        assert get_user(client).is_authenticated is False
