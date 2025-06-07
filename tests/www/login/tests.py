from functools import partial
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
import respx
from django.contrib import messages
from django.test import override_settings
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils.html import escape
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.openid_connect.france_connect import constants as fc_constants
from itou.users import enums as users_enums
from itou.users.enums import IDENTITY_PROVIDER_SUPPORTED_USER_KIND, IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.utils.urls import add_url_params
from itou.www.login.constants import ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY
from itou.www.login.forms import ItouLoginForm
from itou.www.login.views import ExistingUserLoginView
from tests.openid_connect.france_connect.tests import FC_USERINFO, mock_oauth_dance
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)
from tests.utils.test import parse_response_to_soup, pretty_indented, reload_module


PRO_CONNECT_BTN = 'class="proconnect-button"'


class TestItouLogin:
    def test_generic_view(self, client):
        # If a user type cannot be determined, don't prevent login.
        # Just show a generic login form.
        user = JobSeekerFactory()
        url = reverse("account_login")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))


class TestItouLoginForm:
    def test_error_if_user_has_sso_provider(self):
        """
        A user has created an account with another identity provider but tries to connect with Django.
        He should not be able to do it.
        You may wonder how does he know his password? Not that simple but possible.
        This clever user reset his password AND confirmed his e-mail. Voilà.
        We should block him upstream but this means hard work (overriding default Allauth views),
        too long for this quite uncommon use case.
        """
        user = JobSeekerFactory(identity_provider=users_enums.IdentityProvider.FRANCE_CONNECT)
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        form = ItouLoginForm(data=form_data, request=RequestFactory().get("/"))
        assert not form.is_valid()
        assert "FranceConnect" in form.errors["__all__"][0]


class TestPrescriberLogin:
    def test_login_options(self, client, pro_connect):
        url = reverse("login:prescriber")
        response = client.get(url)
        pro_connect.assertContainsButton(response)
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": url,
        }
        pro_connect_url = escape(add_url_params(pro_connect.authorize_url, params))
        assertContains(response, pro_connect_url + '"')
        assertContains(response, "Adresse e-mail")
        assertContains(response, "Mot de passe")

        url_with_next = reverse("login:prescriber", query={"next": "/next_url"})
        response = client.get(url_with_next)
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": url_with_next,
            "next_url": "/next_url",
        }
        pro_connect_url = escape(add_url_params(pro_connect.authorize_url, params))
        assertContains(response, pro_connect_url + '"')

    def test_login_using_django(self, client, pro_connect):
        user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        url = reverse("login:prescriber")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_login_using_django_with_sso_provider(self, client, pro_connect, settings):
        user = PrescriberFactory()
        url = reverse("login:prescriber")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertContains(
            response,
            "Votre compte est relié à ProConnect. Merci de vous connecter avec ce service.",
        )

        # It's possible if we allow it
        settings.FORCE_PROCONNECT_LOGIN = False
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_rate_limits(self, client):
        user = PrescriberFactory()
        url = reverse("login:prescriber")
        form_data = {
            "login": user.email,
            "password": "wrong_password",
        }
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)


class TestEmployerLogin:
    def test_login_options(self, client, pro_connect):
        url = reverse("login:employer")
        response = client.get(url)
        assertContains(response, 'class="proconnect-button"')
        params = {
            "user_kind": UserKind.EMPLOYER,
            "previous_url": url,
        }
        pro_connect_url = escape(reverse("pro_connect:authorize", query=params))
        assertContains(response, pro_connect_url + '"')
        assertContains(response, "Adresse e-mail")
        assertContains(response, "Mot de passe")

        url_with_next = reverse("login:employer", query={"next": "/next_url"})
        response = client.get(url_with_next)
        params = {
            "user_kind": UserKind.EMPLOYER,
            "previous_url": url_with_next,
            "next_url": "/next_url",
        }
        pro_connect_url = escape(reverse("pro_connect:authorize", query=params))
        assertContains(response, pro_connect_url + '"')

    def test_login_using_django(self, client, pro_connect):
        user = EmployerFactory(identity_provider=IdentityProvider.DJANGO)
        url = reverse("login:employer")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_login_using_django_with_sso_provider(self, client, pro_connect, settings):
        user = EmployerFactory()
        url = reverse("login:employer")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertContains(
            response,
            "Votre compte est relié à ProConnect. Merci de vous connecter avec ce service.",
        )

        # It's possible if we allow it
        settings.FORCE_PROCONNECT_LOGIN = False
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_rate_limits(self, client):
        user = EmployerFactory()
        url = reverse("login:employer")
        form_data = {
            "login": user.email,
            "password": "wrong_password",
        }
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)


class TestLaborInspectorLogin:
    def test_login_options(self, client):
        url = reverse("login:labor_inspector")
        response = client.get(url)
        assertNotContains(response, PRO_CONNECT_BTN)
        assertContains(response, "Adresse e-mail")
        assertContains(response, "Mot de passe")

    def test_login(self, client):
        user = LaborInspectorFactory()
        url = reverse("login:labor_inspector")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_rate_limits(self, client):
        user = LaborInspectorFactory()
        url = reverse("login:labor_inspector")
        form_data = {
            "login": user.email,
            "password": "wrong_password",
        }
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)


class TestJobSeekerPreLogin:
    def test_pre_login_email_invalid(self, client):
        form_data = {"email": "emailinvalid"}
        response = client.post(reverse("login:job_seeker"), data=form_data)
        assert response.status_code == 200
        assert response.context["form"].errors["email"] == ["Saisissez une adresse e-mail valide."]

    def test_pre_login_redirects_to_existing_user(self, client):
        user = JobSeekerFactory()
        url = reverse("login:job_seeker")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {"email": user.email}
        response = client.post(url, data=form_data)
        assertRedirects(response, f"{reverse('login:existing_user', args=(user.public_id,))}?back_url={url}")

        # Email is populated in session. The utility of this is covered by the ExistingUserLoginView tests.
        assert client.session[ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY] == user.email

    def test_pre_login_email_unknown(self, client, snapshot):
        url = reverse("login:job_seeker")
        response = client.get(url)

        form_data = {"email": "doesnotexist@test.fr"}
        response = client.post(url, data=form_data)
        assert response.status_code == 200

        assert response.context["form"].errors["email"] == [
            "Cette adresse e-mail est inconnue. Veuillez en saisir une autre, ou vous inscrire."
        ]
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])
        assertContains(response, reverse("signup:job_seeker_start"))

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
        response = mock_oauth_dance(client, expected_route="login:job_seeker")
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

    def test_rate_limits(self, client):
        user = JobSeekerFactory()
        url = reverse("login:job_seeker")
        form_data = {
            "login": user.email,
            "password": "wrong_password",
        }
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)


class TestExistingUserLogin:
    UNSUPPORTED_IDENTITY_PROVIDER_TEXT = "Le mode de connexion associé à ce compte est désactivé"

    def test_hypothetical_identity_provider_failure(self, client):
        # test_login ensures that every IdentityProvider is supported by the existing-login view
        # it relies on the assumption that UNSUPPORTED_IDENTITY_PROVIDER_TEXT is displayed when it is not
        # this is a test for that assumption
        def override_identity_provider_in_context(self, **kwargs):
            context = super(ExistingUserLoginView, self).get_context_data(**kwargs)
            context["login_provider"] = "somethingInvalid"
            return context

        user = JobSeekerFactory()
        with patch.object(ExistingUserLoginView, "get_context_data", override_identity_provider_in_context):
            response = client.get(reverse("login:existing_user", args=(user.public_id,)))
            assertContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)

    @pytest.mark.parametrize(
        "identity_provider",
        [
            IdentityProvider.DJANGO,
            IdentityProvider.FRANCE_CONNECT,
            IdentityProvider.PE_CONNECT,
            IdentityProvider.PRO_CONNECT,
        ],
    )
    @override_settings(
        FRANCE_CONNECT_BASE_URL="http://localhost:8080",
        PEAMU_AUTH_BASE_URL="http://localhost:8080",
        PRO_CONNECT_BASE_URL="http://localhost:8080",
    )
    def test_login(self, client, snapshot, identity_provider):
        # Renders only the component for the identity provider in-use by this account
        user_kind = IDENTITY_PROVIDER_SUPPORTED_USER_KIND[identity_provider][0]
        user = UserFactory(kind=user_kind, identity_provider=identity_provider, for_snapshot=True)
        url = f"{reverse('login:existing_user', args=(user.public_id,))}?back_url={reverse('signup:choose_user_kind')}"
        response = client.get(url)
        assertNotContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)
        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot

    @pytest.mark.parametrize(
        "user_factory",
        [
            JobSeekerFactory,
            PrescriberFactory,
            partial(EmployerFactory, with_company=True),
            LaborInspectorFactory,
            ItouStaffFactory,
        ],
    )
    def test_login_django(self, client, user_factory):
        user = user_factory(identity_provider=IdentityProvider.DJANGO)
        url = reverse("login:existing_user", args=(user.public_id,))
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

    def test_login_email_prefilled(self, client, snapshot):
        # Login is not pre-filled just by visiting the page.
        # The user must prove they know this information
        user = JobSeekerFactory(identity_provider=IdentityProvider.DJANGO, for_snapshot=True)
        url = reverse("login:existing_user", args=(user.public_id,))
        response = client.get(url)
        assert response.status_code == 200

        assert response.context["form"]["login"].initial is None
        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot(
            name="login_not_prefilled"
        )

        # If the email has been populated in the session, but the email populated does not match the user requested,
        # then it is ignored.
        session = client.session
        session[ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY] = "someoneelse@emaildomain.xyz"
        session.save()
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["form"]["login"].initial is None
        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot(
            name="login_not_prefilled"
        )

        # If the login has been populated in the session with the correct email,
        # then the user will not need to re-enter it a second time.
        session[ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY] = user.email
        session.save()
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["form"]["login"].initial == user.email
        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot(
            name="login_prefilled"
        )

    @pytest.mark.parametrize(
        "identity_provider",
        [
            IdentityProvider.DJANGO,
            IdentityProvider.FRANCE_CONNECT,
            IdentityProvider.PE_CONNECT,
            IdentityProvider.PRO_CONNECT,
        ],
    )
    @override_settings(
        FRANCE_CONNECT_BASE_URL=None,
        PEAMU_AUTH_BASE_URL=None,
        PRO_CONNECT_BASE_URL=None,
    )
    def test_login_disabled_provider(self, client, snapshot, identity_provider):
        user_kind = IDENTITY_PROVIDER_SUPPORTED_USER_KIND[identity_provider][0]
        user = UserFactory(kind=user_kind, identity_provider=identity_provider, for_snapshot=True)
        response = client.get(reverse("login:existing_user", args=(user.public_id,)))
        assertNotContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)
        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot

    def test_login_404(self, client):
        response = client.get(reverse("login:existing_user", args=("c0fee70e-cf34-4d37-919d-a1ae3e3bf7e5",)))
        assert response.status_code == 404


def test_prescriber_account_activation_view_with_next(client, pro_connect):
    user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
    client.force_login(user)

    url = reverse("dashboard:activate_pro_connect_account")
    response = client.get(url)
    # Check the href link
    params = {
        "user_kind": UserKind.PRESCRIBER,
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


def test_employer_account_activation_view(client, pro_connect):
    user = EmployerFactory(with_company=True, identity_provider=IdentityProvider.DJANGO)
    client.force_login(user)

    url = reverse("dashboard:activate_pro_connect_account")
    response = client.get(url)
    # Check the href link
    params = {
        "user_kind": UserKind.EMPLOYER,
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
    def test_login_options(self, client):
        url = reverse("login:itou_staff")
        response = client.get(url)
        assertNotContains(response, PRO_CONNECT_BTN)
        assertContains(response, "Adresse e-mail")
        assertContains(response, "Mot de passe")

    def test_login(self, client, settings):
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        login_url = reverse("login:itou_staff")
        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        verify_otp_url = reverse("login:verify_otp")
        setup_otp_url = reverse("itou_staff_views:otp_devices")
        settings.REQUIRE_OTP_FOR_STAFF = True

        response = client.get(admin_url)
        next_url = add_url_params(login_url, {"next": admin_url})
        assertRedirects(response, next_url)

        # Without a device, the user is redirected to the otp setup page
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(next_url, data=form_data, follow=True)
        assertRedirects(response, setup_otp_url)

        # Same with an unconfirmed device
        device = TOTPDevice.objects.create(user=user, confirmed=False)
        response = client.post(next_url, data=form_data, follow=True)
        assertRedirects(response, setup_otp_url)

        # With a confirmed device the user is redirected to the OTP code form
        device.confirmed = True
        device.save()
        response = client.post(next_url, data=form_data, follow=True)
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
        login_url = reverse("login:itou_staff")
        admin_url = reverse("admin:users_user_change", args=(user.pk,))

        response = client.get(admin_url)
        next_url = add_url_params(login_url, {"next": admin_url})
        assertRedirects(response, next_url)

        # Without a device, the user is logged and redirected to the next_url
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(next_url, data=form_data, follow=True)
        assertRedirects(response, admin_url)

        # Same with an device
        TOTPDevice.objects.create(user=user)
        response = client.post(next_url, data=form_data, follow=True)
        assertRedirects(response, admin_url)

    def test_rate_limits(self, client):
        user = ItouStaffFactory()
        url = reverse("login:itou_staff")
        form_data = {
            "login": user.email,
            "password": "wrong_password",
        }
        with freeze_time("2024-09-12T00:00:00Z"):
            # Default rate limit is 30 requests per minute
            for i in range(30):
                response = client.post(url, data=form_data)
                assert response.status_code == 200
            response = client.post(url, data=form_data)
            assertContains(response, "trop de requêtes", status_code=429)
