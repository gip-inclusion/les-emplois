from unittest.mock import patch
from urllib.parse import urlencode

import pytest
import respx
from django.contrib import messages
from django.test import override_settings
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.openid_connect.france_connect import constants as fc_constants
from itou.users import enums as users_enums
from itou.users.enums import IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.utils.urls import add_url_params
from itou.www.login.forms import ItouLoginForm
from itou.www.login.views import ExistingUserLoginView
from tests.openid_connect.france_connect.tests import FC_USERINFO, mock_oauth_dance
from tests.openid_connect.test import sso_parametrize
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)
from tests.utils.test import parse_response_to_soup, reload_module


CONNECT_WITH_IC = "Se connecter avec Inclusion Connect"
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
    @sso_parametrize
    def test_login_options(self, client, sso_setup):
        url = reverse("login:prescriber")
        response = client.get(url)
        sso_setup.assertContainsButton(response)
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": url,
        }
        sso_url = escape(add_url_params(sso_setup.authorize_url, params))
        assertContains(response, sso_url + '"')
        assertContains(response, "Adresse e-mail")
        assertContains(response, "Mot de passe")

        url_with_next = add_url_params(reverse("login:prescriber"), {"next": "/next_url"})
        response = client.get(url_with_next)
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": url_with_next,
            "next_url": "/next_url",
        }
        sso_url = escape(add_url_params(sso_setup.authorize_url, params))
        assertContains(response, sso_url + '"')

    @sso_parametrize
    def test_login_using_django(self, client, sso_setup):
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

    @sso_parametrize
    def test_login_using_django_but_has_sso_provider(self, client, sso_setup):
        user = PrescriberFactory(identity_provider=sso_setup.identity_provider)
        url = reverse("login:prescriber")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": "a",
        }
        response = client.post(url, data=form_data)
        assertContains(
            response,
            "Votre compte est relié à ProConnect. Merci de vous connecter avec ce service.",
        )


class TestEmployerLogin:
    @sso_parametrize
    def test_login_options(self, client, sso_setup):
        url = reverse("login:employer")
        response = client.get(url)
        sso_setup.assertContainsButton(response)
        params = {
            "user_kind": UserKind.EMPLOYER,
            "previous_url": url,
        }
        inclusion_connect_url = escape(add_url_params(sso_setup.authorize_url, params))
        assertContains(response, inclusion_connect_url + '"')
        assertContains(response, "Adresse e-mail")
        assertContains(response, "Mot de passe")

        url_with_next = add_url_params(reverse("login:employer"), {"next": "/next_url"})
        response = client.get(url_with_next)
        params = {
            "user_kind": UserKind.EMPLOYER,
            "previous_url": url_with_next,
            "next_url": "/next_url",
        }
        inclusion_connect_url = escape(add_url_params(sso_setup.authorize_url, params))
        assertContains(response, inclusion_connect_url + '"')

    @sso_parametrize
    def test_login_using_django(self, client, sso_setup):
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

    @sso_parametrize
    def test_login_using_django_but_has_sso_provider(self, client, sso_setup):
        user = EmployerFactory(identity_provider=sso_setup.identity_provider)
        url = reverse("login:employer")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": "a",
        }
        response = client.post(url, data=form_data)
        assertContains(
            response,
            "Votre compte est relié à ProConnect. Merci de vous connecter avec ce service.",
        )


class TestLaborInspectorLogin:
    def test_login_options(self, client):
        url = reverse("login:labor_inspector")
        response = client.get(url)
        assertNotContains(response, CONNECT_WITH_IC)
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


class TestJopbSeekerLogin:
    def test_login(self, client):
        user = JobSeekerFactory()
        url = reverse("login:job_seeker")
        response = client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=form_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

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

    @pytest.mark.parametrize("identity_provider", IdentityProvider.values)
    @override_settings(
        FRANCE_CONNECT_BASE_URL="http://localhost:8080",
        PEAMU_AUTH_BASE_URL="http://localhost:8080",
        INCLUSION_CONNECT_BASE_URL="http://localhost:8080",
        PRO_CONNECT_BASE_URL="http://localhost:8080",
    )
    def test_login(self, client, snapshot, identity_provider):
        # Renders only the component for the identity provider in-use by this account
        user_kind = IdentityProvider.supported_user_kinds[identity_provider][0]
        user = UserFactory(kind=user_kind, identity_provider=identity_provider, for_snapshot=True)
        url = f'{reverse("login:existing_user", args=(user.public_id,))}?back_url={reverse("signup:choose_user_kind")}'
        response = client.get(url)
        assertNotContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)
        assert str(parse_response_to_soup(response, selector=".c-form")) == snapshot

    @pytest.mark.parametrize(
        "identity_provider",
        [
            IdentityProvider.FRANCE_CONNECT,
            IdentityProvider.PE_CONNECT,
            IdentityProvider.PRO_CONNECT,
            IdentityProvider.INCLUSION_CONNECT,
        ],
    )
    @override_settings(
        FRANCE_CONNECT_BASE_URL=None,
        PEAMU_AUTH_BASE_URL=None,
        INCLUSION_CONNECT_BASE_URL=None,
        PRO_CONNECT_BASE_URL=None,
    )
    def test_login_disabled_provider(self, client, snapshot, identity_provider):
        user_kind = IdentityProvider.supported_user_kinds[identity_provider][0]
        user = UserFactory(kind=user_kind, identity_provider=identity_provider, for_snapshot=True)
        response = client.get(reverse("login:existing_user", args=(user.public_id,)))
        assertNotContains(response, self.UNSUPPORTED_IDENTITY_PROVIDER_TEXT)
        assert str(parse_response_to_soup(response, selector=".c-form")) == snapshot

    def test_login_404(self, client):
        response = client.get(reverse("login:existing_user", args=("c0fee70e-cf34-4d37-919d-a1ae3e3bf7e5",)))
        assert response.status_code == 404


def test_prescriber_account_activation_view_with_next(client):
    user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
    client.force_login(user)

    url = reverse("dashboard:activate_ic_account")
    response = client.get(url)
    # Check the href link
    params = {
        "user_kind": UserKind.PRESCRIBER,
        "previous_url": url,
        "user_email": user.email,
    }
    ic_auhtorize_url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    assertContains(response, f'{ic_auhtorize_url}"')

    next_url = "/test_join"
    url = f"{reverse('dashboard:activate_ic_account')}?{urlencode({'next': next_url})}"
    response = client.get(url)
    # Check the href link
    params["previous_url"] = url
    params["next_url"] = next_url
    ic_auhtorize_url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    assertContains(response, f'{ic_auhtorize_url}"')


def test_employer_account_activation_view(client):
    user = EmployerFactory(with_company=True, identity_provider=IdentityProvider.DJANGO)
    client.force_login(user)

    url = reverse("dashboard:activate_ic_account")
    response = client.get(url)
    # Check the href link
    params = {
        "user_kind": UserKind.EMPLOYER,
        "previous_url": url,
        "user_email": user.email,
    }
    ic_auhtorize_url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    assertContains(response, f'{ic_auhtorize_url}"')

    next_url = "/test_join"
    url = f"{reverse('dashboard:activate_ic_account')}?{urlencode({'next': next_url})}"
    response = client.get(url)
    # Check the href link
    params["previous_url"] = url
    params["next_url"] = next_url
    ic_auhtorize_url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
