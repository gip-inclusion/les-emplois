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
from django.contrib.messages import Message
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertQuerySetEqual, assertRedirects

from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.openid_connect.inclusion_connect import constants
from itou.openid_connect.inclusion_connect.enums import InclusionConnectChannel
from itou.openid_connect.inclusion_connect.models import (
    InclusionConnectEmployerData,
    InclusionConnectPrescriberData,
    InclusionConnectState,
)
from itou.openid_connect.inclusion_connect.views import InclusionConnectSession
from itou.openid_connect.models import EmailInUseException, InvalidKindException
from itou.prescribers.models import PrescriberOrganization
from itou.users import enums as users_enums
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.templatetags.theme_inclusion import static_theme_images
from itou.utils.urls import add_url_params, get_absolute_url
from tests.job_applications.factories import JobApplicationSentByPrescriberPoleEmploiFactory
from tests.openid_connect.inclusion_connect.test import (
    OIDC_USERINFO,
    OIDC_USERINFO_FT_WITH_SAFIR,
    assert_and_mock_forced_logout,
    inclusion_connect_setup,
    mock_oauth_dance,
)
from tests.openid_connect.pro_connect.test import pro_connect_setup
from tests.prescribers.factories import PrescriberPoleEmploiFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)


@pytest.fixture(autouse=True)
def setup_ic():
    with inclusion_connect_setup():
        yield


class TestInclusionConnectModel:
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

    def test_join_org(self, caplog):
        # New membership.
        organization = PrescriberPoleEmploiFactory()
        assert organization.active_members.count() == 0
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        user, _ = ic_user_data.create_or_update_user()
        ic_user_data.join_org(user=user, safir=organization.code_safir_pole_emploi)

        assert organization.active_members.count() == 1
        assert organization.has_admin(user)

        # User is already a member.
        ic_user_data.join_org(user=user, safir=organization.code_safir_pole_emploi)
        assert organization.active_members.count() == 1
        assert organization.has_admin(user)

        # Oganization does not exist.
        safir = "12345"
        with pytest.raises(PrescriberOrganization.DoesNotExist):
            ic_user_data.join_org(user=user, safir=safir)
        assert f"Organization with SAFIR {safir} does not exist. Unable to add user {user.id}." in caplog.messages[0]

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

    def test_get_existing_user_with_same_email_IC(self):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        PrescriberFactory(
            username="another_username",
            email=ic_user_data.email,
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        with pytest.raises(EmailInUseException):
            ic_user_data.create_or_update_user()

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


class TestInclusionConnectAuthorizeView:
    def test_authorize_endpoint(self, client):
        url = reverse("inclusion_connect:authorize")
        response = client.get(url, follow=False)
        assertRedirects(response, reverse("search:employers_home"))

        url = f"{reverse('inclusion_connect:authorize')}?user_kind={UserKind.PRESCRIBER}"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in client.session

    def test_authorize_endpoint_for_registration(self, client):
        url = reverse("inclusion_connect:authorize")
        response = client.get(url, follow=False)
        assertRedirects(response, reverse("search:employers_home"))

        url = f"{reverse('inclusion_connect:authorize')}?user_kind={UserKind.PRESCRIBER}&register=true"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_REGISTER)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in client.session

    def test_authorize_endpoint_with_params(self, client):
        email = "porthos@touspourun.com"
        params = {"user_email": email, "user_kind": UserKind.PRESCRIBER, "channel": "invitation"}
        url = f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}"
        response = client.get(url, follow=False)
        assert f"login_hint={quote(email)}" in response.url
        ic_state = InclusionConnectState.get_from_state(
            client.session[constants.INCLUSION_CONNECT_SESSION_KEY]["state"]
        )
        assert ic_state.data["user_email"] == email

    def test_authorize_check_user_kind(self, client, subtests):
        forbidden_user_kinds = [UserKind.ITOU_STAFF, UserKind.LABOR_INSPECTOR, UserKind.JOB_SEEKER]
        for kind in forbidden_user_kinds:
            with subtests.test(kind=kind.label):
                url = f"{reverse('inclusion_connect:authorize')}?user_kind={kind}"
                response = client.get(url)
                assertRedirects(response, reverse("search:employers_home"))

    def test_next_url(self, client, caplog):
        url = f"{reverse('inclusion_connect:authorize')}?{urlencode({'next_url': 'https://external.url.com'})}"
        response = client.get(url, follow=False)
        assertRedirects(response, reverse("search:employers_home"))
        assert caplog.records[0].message == "Forbidden external url"


class TestInclusionConnectCallbackViewTest:
    @respx.mock
    def test_callback_invalid_state(self, client):
        token_json = {"access_token": "access_token", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
        respx.post(constants.INCLUSION_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

        url = reverse("inclusion_connect:callback")
        response = client.get(url, data={"code": "123", "state": "000"})
        assert response.status_code == 302

    def test_callback_no_state(self, client):
        url = reverse("inclusion_connect:callback")
        response = client.get(url, data={"code": "123"})
        assert response.status_code == 302

    def test_callback_no_code(sel, client):
        url = reverse("inclusion_connect:callback")
        response = client.get(url)
        assert response.status_code == 302

    @respx.mock
    def test_callback_prescriber_created(self, client):
        ### User does not exist.
        mock_oauth_dance(client, UserKind.PRESCRIBER)
        assert User.objects.count() == 1
        user = User.objects.get(email=OIDC_USERINFO["email"])
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.kind == "prescriber"
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    @respx.mock
    def test_callback_employer_created(self, client):
        ### User does not exist.
        mock_oauth_dance(client, UserKind.EMPLOYER)
        assert User.objects.count() == 1
        user = User.objects.get(email=OIDC_USERINFO["email"])
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.kind == UserKind.EMPLOYER
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    @respx.mock
    def test_callback_existing_django_user(self, client):
        # User created with django already exists on Itou but some attributes differs.
        # Update all fields
        PrescriberFactory(
            first_name="Bernard",
            last_name="Blier",
            username="bernard_blier",
            email=OIDC_USERINFO["email"],
            identity_provider=users_enums.IdentityProvider.DJANGO,
        )
        mock_oauth_dance(client, UserKind.PRESCRIBER)
        assert User.objects.count() == 1
        user = User.objects.get(email=OIDC_USERINFO["email"])
        assert user.first_name == OIDC_USERINFO["given_name"]
        assert user.last_name == OIDC_USERINFO["family_name"]
        assert user.username == OIDC_USERINFO["sub"]
        assert user.has_sso_provider
        assert user.identity_provider == users_enums.IdentityProvider.INCLUSION_CONNECT

    @respx.mock
    def test_callback_allows_employer_on_prescriber_login_only(self, client):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=UserKind.EMPLOYER)

        response = mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            expected_redirect_url=add_url_params(
                reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:employers_home")}
            ),
        )
        response = client.get(reverse("search:employers_home"))
        assertContains(response, "existe déjà avec cette adresse e-mail")
        assertContains(response, "pour devenir prescripteur sur la plateforme")
        assert get_user(client).is_authenticated is False

        response = mock_oauth_dance(client, UserKind.PRESCRIBER, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.EMPLOYER
        assert get_user(client).is_authenticated is True

    @respx.mock
    def test_callback_allows_prescriber_on_employer_login_only(self, client):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)
        user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=UserKind.PRESCRIBER)

        response = mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            expected_redirect_url=add_url_params(
                reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:employers_home")}
            ),
        )
        response = client.get(reverse("search:employers_home"))
        assertContains(response, "existe déjà avec cette adresse e-mail")
        assertContains(response, "pour devenir employeur sur la plateforme")
        assert get_user(client).is_authenticated is False

        response = mock_oauth_dance(client, UserKind.EMPLOYER, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.PRESCRIBER
        assert get_user(client).is_authenticated is True

    @respx.mock
    def test_callback_refuses_job_seekers(self, client):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)
        user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=UserKind.JOB_SEEKER)

        expected_redirect_url = add_url_params(
            reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:employers_home")}
        )

        mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=expected_redirect_url)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

        mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=expected_redirect_url, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

        mock_oauth_dance(client, UserKind.EMPLOYER, expected_redirect_url=expected_redirect_url)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

        mock_oauth_dance(client, UserKind.EMPLOYER, expected_redirect_url=expected_redirect_url, register=False)
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER
        assert get_user(client).is_authenticated is False

    @respx.mock
    def test_callback_redirect_prescriber_on_too_many_kind_exception(self, client):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        for kind in [UserKind.JOB_SEEKER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=kind)
            response = mock_oauth_dance(
                client,
                UserKind.PRESCRIBER,
                expected_redirect_url=add_url_params(
                    reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:employers_home")}
                ),
            )
            response = client.get(reverse("search:employers_home"))
            assertContains(response, "existe déjà avec cette adresse e-mail")
            assertContains(response, "pour devenir prescripteur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_redirect_employer_on_too_many_kind_exception(self, client):
        ic_user_data = InclusionConnectEmployerData.from_user_info(OIDC_USERINFO)

        for kind in [UserKind.JOB_SEEKER, UserKind.LABOR_INSPECTOR]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, kind=kind)
            # Don't check redirection as the user isn't an siae member yet, so it won't work.
            response = mock_oauth_dance(
                client,
                UserKind.EMPLOYER,
                expected_redirect_url=add_url_params(
                    reverse("inclusion_connect:logout"), {"redirect_url": reverse("search:employers_home")}
                ),
            )
            response = client.get(reverse("search:employers_home"))
            assertContains(response, "existe déjà avec cette adresse e-mail")
            assertContains(response, "pour devenir employeur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_updating_email_collision(self, client):
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
        client.force_login(user)
        edit_user_info_url = reverse("dashboard:edit_user_info")
        response = mock_oauth_dance(client, UserKind.PRESCRIBER, next_url=edit_user_info_url)
        response = client.get(response.url, follow=True)
        assertMessages(
            response,
            [
                Message(
                    messages.ERROR,
                    "Vous avez modifié votre e-mail sur Inclusion Connect, mais celui-ci est déjà associé à un compte "
                    "sur la plateforme. Nous n'avons donc pas pu mettre à jour random@email.com en "
                    f"{OIDC_USERINFO['email']}. Veuillez vous rapprocher du support pour débloquer la situation en "
                    f"suivant <a href='{ global_constants.ITOU_HELP_CENTER_URL }'>ce lien</a>.",
                )
            ],
        )

    @respx.mock
    def test_callback_update_FT_organization(self, client):
        user = PrescriberFactory(**dataclasses.asdict(InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)))
        org = PrescriberPoleEmploiFactory(code_safir_pole_emploi=OIDC_USERINFO_FT_WITH_SAFIR["structure_pe"])
        assert not org.members.exists()

        mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=OIDC_USERINFO_FT_WITH_SAFIR.copy(),
        )
        assertQuerySetEqual(org.members.all(), [user])

    @respx.mock
    def test_callback_update_FT_organization_as_employer_does_not_crash(self, client):
        org = PrescriberPoleEmploiFactory(code_safir_pole_emploi=OIDC_USERINFO_FT_WITH_SAFIR["structure_pe"])
        mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            oidc_userinfo=OIDC_USERINFO_FT_WITH_SAFIR.copy(),
        )
        user = get_user(client)
        assert user.is_authenticated
        assert not user.prescribermembership_set.exists()

        # If he's a prescriber and uses the employer login button
        user.kind = UserKind.PRESCRIBER
        user.save()
        client.logout()
        mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            oidc_userinfo=OIDC_USERINFO_FT_WITH_SAFIR.copy(),
            register=False,
        )
        user = get_user(client)
        assert user.is_authenticated
        assertQuerySetEqual(org.members.all(), [user])

    @respx.mock
    def test_callback_ft_users_with_no_org(self, client):
        PrescriberFactory(**dataclasses.asdict(InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)))

        oidc_userinfo = OIDC_USERINFO.copy()
        oidc_userinfo["email"] = "prenom.nom@francetravail.fr"
        response = mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=oidc_userinfo,
        )
        response = assert_and_mock_forced_logout(client, response)
        assert get_user(client).is_authenticated is False
        assertMessages(
            response,
            [
                Message(
                    messages.WARNING,
                    "En tant qu'agent France Travail vous devez appartenir à une agence pour vous connecter à la "
                    "plateforme des emplois. Veuillez vous faire inviter par l'administrateur d'une agence afin "
                    "d'accéder au service.",
                ),
            ],
        )

    @respx.mock
    def test_callback_ft_users_unknown_safir(self, client):
        PrescriberFactory(**dataclasses.asdict(InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)))

        oidc_userinfo = OIDC_USERINFO_FT_WITH_SAFIR.copy()
        response = mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            oidc_userinfo=oidc_userinfo,
        )
        response = assert_and_mock_forced_logout(client, response)
        assert get_user(client).is_authenticated is False
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
                Message(
                    messages.WARNING,
                    "En tant qu'agent France Travail vous devez appartenir à une agence pour vous connecter à la "
                    "plateforme des emplois. Veuillez vous faire inviter par l'administrateur d'une agence afin "
                    "d'accéder au service.",
                ),
            ],
        )

    @respx.mock
    def test_callback_ft_users_unknown_safir_already_in_org(self, client):
        user = PrescriberFactory(**dataclasses.asdict(InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)))
        org = PrescriberPoleEmploiFactory(code_safir_pole_emploi="00000")
        org.add_or_activate_member(user)

        oidc_userinfo = OIDC_USERINFO_FT_WITH_SAFIR.copy()
        oidc_userinfo["email"] = "prenom.nom@francetravail.fr"
        response = mock_oauth_dance(
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


class TestInclusionConnectAccountActivation:
    def test_new_user(self, client):
        params = {"user_email": OIDC_USERINFO["email"], "user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_REGISTER)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in client.session
        assert f"login_hint={quote(OIDC_USERINFO['email'])}" in response.url

    def test_existing_django_user(self, client):
        user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        params = {"user_email": user.email, "user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_ACTIVATE)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in client.session
        assert f"login_hint={quote(user.email)}" in response.url
        assert f"firstname={user.first_name}" in response.url
        assert f"lastname={user.last_name}" in response.url

    def test_existing_ic_user(self, client):
        user = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        params = {"user_email": user.email, "user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = client.get(url, follow=False)
        assert response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)
        assert constants.INCLUSION_CONNECT_SESSION_KEY in client.session
        assert f"login_hint={quote(user.email)}" in response.url

    def test_bad_user_kind(self, client, subtests):
        for user in [JobSeekerFactory(), PrescriberFactory(), EmployerFactory(), LaborInspectorFactory()]:
            user_kind = UserKind.PRESCRIBER if user.kind != UserKind.PRESCRIBER else UserKind.EMPLOYER
            with subtests.test(user_kind=user_kind.label):
                params = {"user_email": user.email, "user_kind": user_kind}
                url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
                response = client.get(url, follow=True)
                assertRedirects(response, reverse("search:employers_home"))
                assertContains(response, "existe déjà avec cette adresse e-mail")
                assertContains(response, "Vous devez créer un compte Inclusion Connect avec une autre adresse e-mail")

    def test_no_email(self, client):
        params = {"user_kind": UserKind.PRESCRIBER}
        url = f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}"
        response = client.get(url)
        assertRedirects(response, reverse("search:employers_home"))


class TestInclusionConnectSession:
    def test_start_session(self, subtests):
        ic_session = InclusionConnectSession()
        assert ic_session.key == constants.INCLUSION_CONNECT_SESSION_KEY

        expected_keys = ["token", "state"]
        ic_session_dict = ic_session.asdict()
        for key in expected_keys:
            with subtests.test(key):
                assert key in ic_session_dict.keys()
                assert ic_session_dict[key] is None

        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()
        ic_session.bind_to_request(request)
        assert request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)


class TestInclusionConnectLogin:
    @respx.mock
    def test_normal_signin(self, client):
        """
        A user has created an account with Inclusion Connect.
        He logs out.
        He can log in again later.
        """
        # Create an account with IC.
        response = mock_oauth_dance(client, UserKind.PRESCRIBER)
        client.get(response.url)  # display welcoming_tour

        # Then log out.
        response = client.post(reverse("account_logout"))

        # Then log in again.
        login_url = reverse("login:prescriber")
        response = client.get(login_url)
        assertContains(response, static_theme_images("logo-inclusion-connect-one-line.svg"))
        assertContains(response, reverse("inclusion_connect:authorize"))

        response = mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))

        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=OIDC_USERINFO["email"]).count()
        assert users_count == 1

    @respx.mock
    def test_old_django_account(self, client):
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
        response = mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))
        assert auth.get_user(client).is_authenticated
        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=OIDC_USERINFO["email"]).count()
        assert users_count == 1

        response = client.post(reverse("account_logout"))
        assert response.status_code == 302
        assert not auth.get_user(client).is_authenticated

        # Try to login with Django.
        # This is already tested in itou.www.login.tests but only at form level.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        response = client.post(reverse("login:prescriber"), data=post_data)
        error_message = "Votre compte est relié à ProConnect."
        assertContains(response, error_message)
        assert not auth.get_user(client).is_authenticated

        # Then login with Inclusion Connect.
        mock_oauth_dance(client, UserKind.PRESCRIBER, expected_redirect_url=reverse("dashboard:index"))
        assert auth.get_user(client).is_authenticated


class TestInclusionConnectLogout:
    @respx.mock
    def test_simple_logout(self, client):
        mock_oauth_dance(client, UserKind.PRESCRIBER)
        logout_url = reverse("inclusion_connect:logout")
        response = client.get(logout_url)
        assertRedirects(
            response,
            add_url_params(
                constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT,
                {
                    "id_token_hint": 123456,
                    "post_logout_redirect_uri": get_absolute_url(reverse("search:employers_home")),
                },
            ),
            fetch_redirect_response=False,
        )

    @respx.mock
    def test_logout_with_redirection(self, client):
        mock_oauth_dance(client, UserKind.PRESCRIBER)
        expected_redirection = reverse("dashboard:index")

        params = {"redirect_url": expected_redirection}
        logout_url = f"{reverse('inclusion_connect:logout')}?{urlencode(params)}"
        response = client.get(logout_url)
        assertRedirects(
            response,
            add_url_params(
                constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT,
                {"id_token_hint": 123456, "post_logout_redirect_uri": get_absolute_url(expected_redirection)},
            ),
            fetch_redirect_response=False,
        )

    @respx.mock
    def test_django_account_logout_from_ic(self, client):
        """
        When ac IC user wants to log out from his local account,
        he should be logged out too from IC.
        """
        response = mock_oauth_dance(client, UserKind.PRESCRIBER)
        assert auth.get_user(client).is_authenticated
        # Follow the redirection.
        response = client.get(response.url)
        logout_url = reverse("account_logout")
        assertContains(response, logout_url)
        assert client.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)

        response = client.post(logout_url)
        expected_redirection = reverse("inclusion_connect:logout")
        # For simplicity, exclude GET params. They are tested elsewhere anyway..
        assert response.url.startswith(expected_redirection)

        response = client.get(response.url)
        # The following redirection is tested in self.test_logout_with_redirection
        assert response.status_code == 302
        assert not auth.get_user(client).is_authenticated

    def test_django_account_logout(self, client):
        """
        When a local user wants to log out from his local account,
        he should be logged out without inclusion connect.
        """
        user = PrescriberFactory()
        client.force_login(user)
        response = client.post(reverse("account_logout"))
        assertRedirects(response, reverse("search:employers_home"))
        assert not auth.get_user(client).is_authenticated

    @respx.mock
    def test_logout_with_incomplete_state(self, client):
        # This happens while testing. It should never happen for real users, but it's still painful for us.

        mock_oauth_dance(client, UserKind.PRESCRIBER)

        session = client.session
        session[constants.INCLUSION_CONNECT_SESSION_KEY]["token"] = None
        session[constants.INCLUSION_CONNECT_SESSION_KEY]["state"] = None
        session.save()

        response = client.post(reverse("account_logout"))
        assertRedirects(response, reverse("search:employers_home"))


class TestInclusionConnectmapChannel:
    @pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
    @respx.mock
    def test_happy_path(self, client):
        job_application = JobApplicationSentByPrescriberPoleEmploiFactory(
            sender_prescriber_organization__code_safir_pole_emploi=OIDC_USERINFO_FT_WITH_SAFIR["structure_pe"]
        )
        prescriber = job_application.sender
        prescriber.email = OIDC_USERINFO["email"]
        prescriber.username = OIDC_USERINFO["sub"]
        prescriber.save()
        url_from_map = "{path}?channel={channel}".format(
            path=reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            channel=InclusionConnectChannel.MAP_CONSEILLER.value,
        )

        response = client.get(url_from_map, follow=True)
        # Starting point of both the oauth_dance and `mock_oauth_dance()`.
        ic_endpoint = response.redirect_chain[-1][0]
        assert ic_endpoint.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)
        assert f"channel={InclusionConnectChannel.MAP_CONSEILLER.value}" in ic_endpoint

        response = mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            next_url=url_from_map,
            expected_redirect_url=url_from_map,
            channel=InclusionConnectChannel.MAP_CONSEILLER,
        )
        assert auth.get_user(client).is_authenticated

        response = client.get(response.url)
        assert response.status_code == 200

    @pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
    @respx.mock
    def test_create_user(self, client):
        # Application sent by a colleague from the same agency but not by the prescriber himself.
        job_application = JobApplicationSentByPrescriberPoleEmploiFactory(
            sender_prescriber_organization__code_safir_pole_emploi=OIDC_USERINFO_FT_WITH_SAFIR["structure_pe"]
        )

        # Prescriber does not belong to this organization on Itou but
        # IC says that he is allowed to join it.
        # A new user should be created automatically, only when coming from MAP conseiller,
        # and then be able to see a job application details.
        url_from_map = "{path}?channel={channel}".format(
            path=reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            channel=InclusionConnectChannel.MAP_CONSEILLER.value,
        )

        response = client.get(url_from_map, follow=True)
        # Starting point of both the oauth_dance and `mock_oauth_dance()`.
        ic_endpoint = response.redirect_chain[-1][0]
        assert ic_endpoint.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)

        response = mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            next_url=url_from_map,
            expected_redirect_url=url_from_map,
            channel=InclusionConnectChannel.MAP_CONSEILLER,
            oidc_userinfo=OIDC_USERINFO_FT_WITH_SAFIR.copy(),
        )
        assert job_application.sender_prescriber_organization.members.count() == 2
        assert auth.get_user(client).is_authenticated

        response = client.get(response.url)
        assert response.status_code == 200

    @respx.mock
    def test_create_user_organization_not_found(self, client):
        # Application sent by a colleague from the same agency but not by the prescriber himself.
        job_application = JobApplicationSentByPrescriberPoleEmploiFactory(
            sender_prescriber_organization__code_safir_pole_emploi=11111
        )

        # Prescriber does not belong to this organization on Itou but
        # IC says that he is allowed to join it.
        # A new user should be created automatically and redirected to the job application details page.
        url_from_map = "{path}?channel={channel}".format(
            path=reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            channel=InclusionConnectChannel.MAP_CONSEILLER.value,
        )

        response = client.get(url_from_map, follow=True)
        # Starting point of both the oauth_dance and `mock_oauth_dance()`.
        ic_endpoint = response.redirect_chain[-1][0]
        assert ic_endpoint.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE)

        response = mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            next_url=url_from_map,
            channel=InclusionConnectChannel.MAP_CONSEILLER,
            oidc_userinfo=OIDC_USERINFO_FT_WITH_SAFIR.copy(),
        )
        response = assert_and_mock_forced_logout(client, response)

        assert job_application.sender_prescriber_organization.members.count() == 1
        assert not auth.get_user(client).is_authenticated

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
                Message(
                    messages.WARNING,
                    "En tant qu'agent France Travail vous devez appartenir à une agence pour vous connecter à la "
                    "plateforme des emplois. Veuillez vous faire inviter par l'administrateur d'une agence afin "
                    "d'accéder au service.",
                ),
            ],
        )


def test_inclusion_connect_is_forbidden_when_pro_connect_is_enabled(client):
    with pro_connect_setup():
        url = f"{reverse('inclusion_connect:authorize')}?user_kind={UserKind.PRESCRIBER}"
        response = client.get(url)
        assertRedirects(response, reverse("search:employers_home"))
        assert constants.INCLUSION_CONNECT_SESSION_KEY not in client.session

        url = f"{reverse('inclusion_connect:callback')}"
        response = client.get(url)
        assertRedirects(response, reverse("search:employers_home"))
        assert constants.INCLUSION_CONNECT_SESSION_KEY not in client.session
