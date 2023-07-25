from urllib.parse import urlencode

import respx
from django.contrib import messages
from django.test import override_settings
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains

from itou.openid_connect.france_connect import constants as fc_constants
from itou.users import enums as users_enums
from itou.users.enums import IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.utils.urls import add_url_params
from itou.www.login.forms import ItouLoginForm
from tests.openid_connect.france_connect.tests import FC_USERINFO, mock_oauth_dance
from tests.openid_connect.inclusion_connect.test import InclusionConnectBaseTestCase
from tests.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    SiaeStaffFactory,
)
from tests.utils.test import TestCase, assertMessages, reload_module


class ItouLoginTest(TestCase):
    def test_generic_view(self):
        # If a user type cannot be determined, don't prevent login.
        # Just show a generic login form.
        user = JobSeekerFactory()
        url = reverse("account_login")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=form_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))


class ItouLoginFormTest(TestCase):
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


class PrescriberLoginTest(InclusionConnectBaseTestCase):
    def test_login_options(self):
        url = reverse("login:prescriber")
        response = self.client.get(url)
        self.assertContains(response, "Se connecter avec Inclusion Connect")
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": url,
        }
        inclusion_connect_url = escape(add_url_params(reverse("inclusion_connect:authorize"), params))
        self.assertContains(response, inclusion_connect_url + '"')
        self.assertContains(response, "Adresse e-mail")
        self.assertContains(response, "Mot de passe")

        url_with_next = add_url_params(reverse("login:prescriber"), {"next": "/next_url"})
        response = self.client.get(url_with_next)
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": url_with_next,
            "next_url": "/next_url",
        }
        inclusion_connect_url = escape(add_url_params(reverse("inclusion_connect:authorize"), params))
        self.assertContains(response, inclusion_connect_url + '"')

    def test_login_using_django(self):
        user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        url = reverse("login:prescriber")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=form_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

    def test_login_using_django_but_has_sso_provider(self):
        user = PrescriberFactory(identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT)
        url = reverse("login:prescriber")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": "a",
        }
        response = self.client.post(url, data=form_data)
        self.assertContains(
            response, "Votre compte est relié à Inclusion Connect. Merci de vous connecter avec ce service."
        )


class SiaeStaffLoginTest(InclusionConnectBaseTestCase):
    def test_login_options(self):
        url = reverse("login:siae_staff")
        response = self.client.get(url)
        self.assertContains(response, "Se connecter avec Inclusion Connect")
        params = {
            "user_kind": UserKind.SIAE_STAFF,
            "previous_url": url,
        }
        inclusion_connect_url = escape(add_url_params(reverse("inclusion_connect:authorize"), params))
        self.assertContains(response, inclusion_connect_url + '"')
        self.assertContains(response, "Adresse e-mail")
        self.assertContains(response, "Mot de passe")

        url_with_next = add_url_params(reverse("login:siae_staff"), {"next": "/next_url"})
        response = self.client.get(url_with_next)
        params = {
            "user_kind": UserKind.SIAE_STAFF,
            "previous_url": url_with_next,
            "next_url": "/next_url",
        }
        inclusion_connect_url = escape(add_url_params(reverse("inclusion_connect:authorize"), params))
        self.assertContains(response, inclusion_connect_url + '"')

    def test_login_using_django(self):
        user = SiaeStaffFactory(identity_provider=IdentityProvider.DJANGO)
        url = reverse("login:siae_staff")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=form_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

    def test_login_using_django_but_has_sso_provider(self):
        user = SiaeStaffFactory(identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT)
        url = reverse("login:siae_staff")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": "a",
        }
        response = self.client.post(url, data=form_data)
        self.assertContains(
            response, "Votre compte est relié à Inclusion Connect. Merci de vous connecter avec ce service."
        )


class LaborInspectorLoginTest(TestCase):
    def test_login_options(self):
        url = reverse("login:labor_inspector")
        response = self.client.get(url)
        self.assertNotContains(response, "S'identifier avec Inclusion Connect")
        self.assertContains(response, "Adresse e-mail")
        self.assertContains(response, "Mot de passe")

    def test_login(self):
        user = LaborInspectorFactory()
        url = reverse("login:labor_inspector")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=form_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))


class JopbSeekerLoginTest(TestCase):
    def test_login(self):
        user = JobSeekerFactory()
        url = reverse("login:job_seeker")
        response = self.client.get(url)
        assert response.status_code == 200

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=form_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

    @respx.mock
    @override_settings(
        FRANCE_CONNECT_BASE_URL="https://france.connect.fake",
        FRANCE_CONNECT_CLIENT_ID="IC_CLIENT_ID_123",
        FRANCE_CONNECT_CLIENT_SECRET="IC_CLIENT_SECRET_123",
    )
    @reload_module(fc_constants)
    def test_conflict_on_email_change_in_france_connect(self):
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
        response = mock_oauth_dance(self.client, expected_route="login:job_seeker")
        assertMessages(
            response,
            [
                (
                    messages.ERROR,
                    "Vous avez deux comptes sur la plateforme et nous détectons un conflit d'email : "
                    "seconde@email.com et wossewodda-3728@yopmail.com. Veuillez vous rapprocher du support pour "
                    "débloquer la situation en suivant "
                    f"<a href='{global_constants.ITOU_HELP_CENTER_URL}'>ce lien</a>.",
                )
            ],
        )


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


def test_siae_staff_account_activation_view(client):
    user = SiaeStaffFactory(with_siae=True, identity_provider=IdentityProvider.DJANGO)
    client.force_login(user)

    url = reverse("dashboard:activate_ic_account")
    response = client.get(url)
    # Check the href link
    params = {
        "user_kind": UserKind.SIAE_STAFF,
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
