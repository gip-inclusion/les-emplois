import random
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
import respx
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django.urls import reverse
from django.utils.html import escape
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from freezegun import freeze_time
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.openid_connect.france_connect import constants as fc_constants
from itou.openid_connect.pe_connect import constants as pe_constants
from itou.users.enums import IdentityProvider
from itou.utils import constants as global_constants
from itou.www.login.constants import ITOU_SESSION_LOGIN_EMAIL_KEY
from itou.www.login.forms import ItouLoginForm
from itou.www.login.views import ExistingUserLoginView
from tests.openid_connect.france_connect.tests import FC_USERINFO, mock_oauth_dance as fc_mock_oauth_dance
from tests.openid_connect.pe_connect.tests import (
    PEAMU_USERINFO,
    TEST_SETTINGS,
    mock_oauth_dance as pe_mock_oauth_dance,
)
from tests.users.factories import (
    DEFAULT_PASSWORD,
    HASHED_DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    random_user_kind_factory,
)
from tests.utils.testing import get_request, parse_response_to_soup, pretty_indented, reload_module


PRO_CONNECT_BTN = 'class="proconnect-button"'


class TestPreLogin:
    def test_pre_login_email_invalid(self, client):
        form_data = {"email": "emailinvalid"}
        response = client.post(reverse("account_login"), data=form_data)
        assert response.status_code == 200
        assert response.context["form"].errors["email"] == ["Saisissez une adresse e-mail valide."]

    def test_pre_login_redirects_to_existing_user(self, client):
        user = random_user_kind_factory()
        url = reverse("account_login")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {"email": user.email}
        response = client.post(url, data=form_data)
        expected_url = reverse(
            "login:existing_user",
            query={"back_url": url},
        )
        assertRedirects(response, expected_url)
        assert client.session[ITOU_SESSION_LOGIN_EMAIL_KEY] == user.email

    def test_pre_login_redirects_to_existing_user_with_next(self, client):
        user = random_user_kind_factory()
        next_url = "/next_url"
        url = reverse("account_login", query={"next": next_url})
        response = client.get(url)
        assert response.status_code == 200

        form_data = {"email": user.email}
        response = client.post(url, data=form_data)
        expected_url = reverse(
            "login:existing_user",
            query={"back_url": url, "next": next_url},
        )
        assertRedirects(response, expected_url)
        assert client.session[ITOU_SESSION_LOGIN_EMAIL_KEY] == user.email

    def test_pre_login_redirects_to_pro_connect(self, client, pro_connect):
        # This only works when ProConnect is configured
        user = random_user_kind_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        url = reverse("account_login")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {"email": user.email}
        response = client.post(url, data=form_data)
        params = {
            "user_kind": user.kind,
            "previous_url": url,
            "user_email": user.email,
        }
        pro_connect_url = add_url_params(pro_connect.authorize_url, params)
        assertRedirects(response, pro_connect_url, fetch_redirect_response=False)

    def test_pre_login_redirects_to_pro_connect_with_next(self, client, pro_connect):
        # This only works when ProConnect is configured
        user = random_user_kind_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        next_url = "/next_url"
        url = reverse("account_login", query={"next": next_url})
        response = client.get(url)
        assert response.status_code == 200

        form_data = {"email": user.email}
        response = client.post(url, data=form_data)
        params = {
            "user_kind": user.kind,
            "previous_url": url,
            "user_email": user.email,
            "next_url": next_url,
        }
        pro_connect_url = add_url_params(pro_connect.authorize_url, params)
        assertRedirects(response, pro_connect_url, fetch_redirect_response=False)

    def test_pre_login_email_unknown(self, client, snapshot):
        url = reverse("account_login")
        response = client.get(url)

        form_data = {"email": "doesnotexist@test.fr"}
        response = client.post(url, data=form_data)
        assert response.status_code == 200

        assert response.context["form"].errors["email"] == [
            "Cette adresse e-mail est inconnue. Veuillez en saisir une autre, ou vous inscrire."
        ]
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])

    def test_rate_limits(self, client):
        url = reverse("account_login")
        form_data = {"email": "any@mailinator.com"}
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)


class TestItouLoginForm:
    @pytest.mark.parametrize("identity_provider", IdentityProvider)
    def test_validate_identity_provider(self, identity_provider):
        """
        If an user has an account using an active identity provider, they should not be able to connect with Django.

        You may wonder how does he know his password? Not that simple but possible.
        This clever user reset his password AND confirmed his e-mail. Voilà.
        We should block him upstream but this means hard work (overriding default Allauth views),
        too long for this quite uncommon use case.
        Or it can be a professional that had a Django account and logged in with ProConnect at some point
        """
        user = random_user_kind_factory(identity_provider=identity_provider, password=HASHED_DEFAULT_PASSWORD)
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        request = get_request(AnonymousUser())
        form = ItouLoginForm(data=form_data, request=request)
        if identity_provider in [IdentityProvider.DJANGO, IdentityProvider.INCLUSION_CONNECT]:
            assert form.is_valid()
        else:
            assert not form.is_valid()
            assert identity_provider.label in form.errors["__all__"][0]


class TestJobSeekerLoginFailures:
    @respx.mock
    @override_settings(
        FRANCE_CONNECT_BASE_URL="https://france.connect.fake",
        FRANCE_CONNECT_CLIENT_ID="IC_CLIENT_ID_123",
        FRANCE_CONNECT_CLIENT_SECRET="IC_CLIENT_SECRET_123",
    )
    @reload_module(fc_constants)
    def test_conflict_on_email_change_in_france_connect(self, client):
        """
        The job seeker has 2 accounts : a django one, and a FC one, with 2 different email adresses.
        Then he changes the email adresse on FC to use the django account email.
        """
        JobSeekerFactory(email=FC_USERINFO["email"], identity_provider=IdentityProvider.DJANGO)
        JobSeekerFactory(
            username=FC_USERINFO["sub"],
            email="seconde@email.com",
            identity_provider=IdentityProvider.FRANCE_CONNECT,
        )

        # Temporary NIR is not stored with user information.
        response = fc_mock_oauth_dance(client, expected_route="account_login")
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Vous avez deux comptes sur la plateforme et nous détectons un conflit d'email : "
                    "seconde@email.com et wossewodda-3728@yopmail.com. Veuillez vous rapprocher du support pour "
                    "débloquer la situation en suivant "
                    f"<a href='{global_constants.ITOU_HELP_CENTER_URL}'>ce lien</a>.",
                )
            ],
        )

    @respx.mock
    @override_settings(**TEST_SETTINGS)
    @reload_module(pe_constants)
    def test_conflict_on_email_change_in_pe_connect(self, client):
        """
        The job seeker has 2 accounts : a django one, and a FC one, with 2 different email adresses.
        Then he changes the email adresse on FC to use the django account email.
        """
        JobSeekerFactory(email=PEAMU_USERINFO["email"], identity_provider=IdentityProvider.DJANGO)
        JobSeekerFactory(
            username=PEAMU_USERINFO["sub"],
            email="seconde@email.com",
            identity_provider=IdentityProvider.PE_CONNECT,
        )

        # Temporary NIR is not stored with user information.
        response = pe_mock_oauth_dance(client, expected_route="account_login")
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Vous avez deux comptes sur la plateforme et nous détectons un conflit d'email : "
                    "seconde@email.com et wossewodda-3728@yopmail.com. Veuillez vous rapprocher du support pour "
                    "débloquer la situation en suivant "
                    f"<a href='{global_constants.ITOU_HELP_CENTER_URL}'>ce lien</a>.",
                )
            ],
        )


class TestExistingUserLogin:
    UNSUPPORTED_IDENTITY_PROVIDER_TEXT = "Le mode de connexion associé à ce compte est désactivé"

    def _get_login_form_cases(self):
        # get data for subtests
        return [
            (
                "DJANGO",
                random.choice([JobSeekerFactory, LaborInspectorFactory, ItouStaffFactory])(
                    identity_provider=IdentityProvider.DJANGO, email="django@mailinator.com"
                ),
            ),
            (
                "DJANGO+PC",
                random.choice([PrescriberFactory, EmployerFactory])(
                    identity_provider=IdentityProvider.DJANGO, email="django+pc@mailinator.com"
                ),
            ),
            (
                "IC",
                random_user_kind_factory(
                    identity_provider=IdentityProvider.INCLUSION_CONNECT, email="ic@mailinator.com"
                ),
            ),
            (
                "PC",
                random_user_kind_factory(identity_provider=IdentityProvider.PRO_CONNECT, email="pc@mailinator.com"),
            ),
            (
                "PE",
                random_user_kind_factory(identity_provider=IdentityProvider.PE_CONNECT, email="pe@mailinator.com"),
            ),
            (
                "FC",
                random_user_kind_factory(identity_provider=IdentityProvider.FRANCE_CONNECT, email="fc@mailinator.com"),
            ),
        ]

    def test_rate_limits(self, client):
        user = random_user_kind_factory(identity_provider=IdentityProvider.DJANGO)
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        url = reverse("login:existing_user")
        form_data = {
            "login": "any@mailinator.com",
            "password": "wrong_password",
        }
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)

    def test_hypothetical_identity_provider_failure(self, client):
        # test_login ensures that every IdentityProvider is supported by the existing-login view
        # it relies on the assumption that UNSUPPORTED_IDENTITY_PROVIDER_TEXT is displayed when it is not
        # this is a test for that assumption
        def override_identity_provider_in_context(self, **kwargs):
            context = super(ExistingUserLoginView, self).get_context_data(**kwargs)
            context["login_provider"] = "somethingInvalid"
            return context

        user = JobSeekerFactory()
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        with patch.object(ExistingUserLoginView, "get_context_data", override_identity_provider_in_context):
            response = client.get(reverse("login:existing_user"))
            assertContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)

    @override_settings(
        FRANCE_CONNECT_BASE_URL="http://localhost:8080",
        PEAMU_AUTH_BASE_URL="http://localhost:8080",
        PRO_CONNECT_BASE_URL="http://localhost:8080",
    )
    def test_login(self, client, snapshot):
        for name, user in self._get_login_form_cases():
            session = client.session
            session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
            session.save()
            url = reverse("login:existing_user")
            response = client.get(url)
            assertNotContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)
            assert pretty_indented(
                parse_response_to_soup(
                    response,
                    selector=".c-form",
                    replace_in_attr=[
                        ("data-matomo-category", "employeur inclusif", "[User kind]"),
                        ("data-matomo-category", "prescripteur", "[User kind]"),
                        ("href", user.kind, "[User kind]"),
                    ],
                )
            ) == snapshot(name=name)

    @pytest.mark.parametrize(
        "user_factory",
        [
            JobSeekerFactory,
            PrescriberFactory,
            EmployerFactory,
            LaborInspectorFactory,
            ItouStaffFactory,
        ],
    )
    def test_login_django(self, client, user_factory):
        user = user_factory(identity_provider=IdentityProvider.DJANGO)
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        url = reverse("login:existing_user")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_login_inclusion_connect(self, client):
        # IC old users have the Django login form
        user = random_user_kind_factory(
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
            password=HASHED_DEFAULT_PASSWORD,
        )
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        url = reverse("login:existing_user")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    @override_settings(
        FRANCE_CONNECT_BASE_URL=None,
        PEAMU_AUTH_BASE_URL=None,
        PRO_CONNECT_BASE_URL=None,
    )
    def test_login_disabled_provider(self, client, snapshot):
        for name, user in self._get_login_form_cases():
            session = client.session
            session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
            session.save()
            response = client.get(reverse("login:existing_user"))
            assertNotContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)
            assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot(name=name)

    def test_login_no_session(self, client):
        response = client.get(reverse("login:existing_user"))
        assertRedirects(response, reverse("account_login"))

    def test_login_unknown_email_in_session(self, client):
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = "john.doe@mailinator.com"
        session.save()
        response = client.get(reverse("login:existing_user"))
        assertRedirects(response, reverse("account_login"))

    def test_pro_connect_user(self, client, pro_connect):
        user = random_user_kind_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        url = reverse("login:existing_user")
        response = client.get(url)
        pro_connect.assertContainsButton(response)
        params = {
            "user_kind": user.kind,
            "previous_url": url,
            "user_email": user.email,
        }
        pro_connect_url = escape(add_url_params(pro_connect.authorize_url, params))
        assertContains(response, pro_connect_url + '"')

        url_with_next = reverse("login:existing_user", query={"next": "/next_url"})
        response = client.get(url_with_next)
        params = {
            "user_kind": user.kind,
            "previous_url": url_with_next,
            "user_email": user.email,
            "next_url": "/next_url",
        }
        pro_connect_url = escape(add_url_params(pro_connect.authorize_url, params))
        assertContains(response, pro_connect_url + '"')


@pytest.mark.parametrize("factory", [PrescriberFactory, EmployerFactory])
def test_pro_connect_activation_view(client, pro_connect, factory):
    user = factory(identity_provider=IdentityProvider.DJANGO, membership=True)
    client.force_login(user)

    url = reverse("dashboard:activate_pro_connect_account")
    response = client.get(url)
    # Check the href link
    params = {
        "user_kind": user.kind,
        "previous_url": url,
        "user_email": user.email,
    }
    pc_auhtorize_url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
    assertContains(response, f'{pc_auhtorize_url}"')

    next_url = "/test_join"
    url = f"{reverse('dashboard:activate_pro_connect_account')}?{urlencode({'next': next_url})}"
    response = client.get(url)
    # Check the href link
    params["previous_url"] = url
    params["next_url"] = next_url
    pc_auhtorize_url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
    assertContains(response, f'{pc_auhtorize_url}"')


class TestItouStaffLogin:
    def test_login(self, client, settings):
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        pre_login_url = add_url_params(reverse("account_login"), {"next": admin_url})
        login_url = add_url_params(
            reverse("login:existing_user"),
            {"back_url": pre_login_url, "next": admin_url},
        )
        verify_otp_url = reverse("login:verify_otp")
        setup_otp_url = reverse("itou_staff_views:otp_devices")
        settings.REQUIRE_OTP_FOR_STAFF = True

        response = client.get(admin_url)
        assertRedirects(response, pre_login_url)

        response = client.post(pre_login_url, {"email": user.email})
        assertRedirects(response, login_url)

        # Without a device, the user is redirected to the otp setup page
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, setup_otp_url)

        # Same with an unconfirmed device
        client.logout()
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        device = TOTPDevice.objects.create(user=user, confirmed=False)
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, setup_otp_url)

        # With a confirmed device the user is redirected to the OTP code form
        device.confirmed = True
        device.save()
        client.logout()
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        response = client.post(login_url, data=form_data, follow=True)
        next_url = add_url_params(verify_otp_url, {"next": admin_url})
        assertRedirects(response, next_url)

        # The user should not be able to access the setup otp pages
        response = client.get(setup_otp_url)
        assertRedirects(response, add_url_params(verify_otp_url, {"next": setup_otp_url}))
        other_device = TOTPDevice.objects.create(user=user, confirmed=False)
        setup_otp_confirm_device_url = reverse("itou_staff_views:otp_confirm_device", args=(other_device.pk,))
        response = client.get(setup_otp_confirm_device_url)
        assertRedirects(response, add_url_params(verify_otp_url, {"next": setup_otp_confirm_device_url}))

        # Give a bad token
        totp = TOTP(device.bin_key, drift=100)
        post_data = {
            "name": "Mon appareil",
            "otp_token": totp.token(),  # a token from a long time ago
        }
        response = client.post(next_url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {"otp_token": ["code invalide"]}

        # there's throttling
        totp = TOTP(device.bin_key)
        post_data["otp_token"] = totp.token()
        response = client.post(next_url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {"otp_token": ["code invalide"]}

        # When resetting the failure count it works
        device.throttling_failure_timestamp = None
        device.throttling_failure_count = 0
        device.save()
        response = client.post(next_url, data=post_data)
        assertRedirects(response, admin_url)

    def test_login_otp_not_required(self, client):
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        pre_login_url = add_url_params(reverse("account_login"), {"next": admin_url})
        login_url = add_url_params(
            reverse("login:existing_user"),
            {"back_url": pre_login_url, "next": admin_url},
        )

        response = client.get(admin_url)
        assertRedirects(response, pre_login_url)

        response = client.post(pre_login_url, {"email": user.email})
        assertRedirects(response, login_url)

        # Without a device, the user is logged and redirected to the next_url
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, admin_url)

        # Same with an device
        client.logout()
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        TOTPDevice.objects.create(user=user)
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, admin_url)
