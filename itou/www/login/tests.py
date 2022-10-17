import respx
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.urls import reverse

from itou.openid_connect.france_connect import constants as fc_constants
from itou.openid_connect.france_connect.tests import FC_USERINFO, mock_oauth_dance
from itou.openid_connect.inclusion_connect.testing import InclusionConnectBaseTestCase
from itou.users import enums as users_enums
from itou.users.enums import IdentityProvider
from itou.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    SiaeStaffFactory,
    UserFactory,
)
from itou.utils.testing import reload_module
from itou.www.login.forms import ItouLoginForm


class ItouLoginTest(TestCase):
    def test_generic_view(self):
        # If a user type cannot be determined, don't prevent login.
        # Just show a generic login form.
        user = JobSeekerFactory()
        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

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
        user = PrescriberFactory(identity_provider=users_enums.IdentityProvider.FRANCE_CONNECT)
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        form = ItouLoginForm(data=form_data, request=RequestFactory().get("/"))
        self.assertFalse(form.is_valid())
        self.assertIn("FranceConnect", form.errors["__all__"][0])


class PrescriberLoginTest(InclusionConnectBaseTestCase):
    def test_login_options(self):
        url = reverse("login:prescriber")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "S'identifier avec Inclusion Connect")
        self.assertContains(response, reverse("inclusion_connect:authorize"))
        self.assertContains(response, "Adresse e-mail")
        self.assertContains(response, "Mot de passe")

    def test_login_using_django(self):
        user = PrescriberFactory()
        url = reverse("login:prescriber")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

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
        self.assertEqual(response.status_code, 200)

        form_data = {
            "login": user.email,
            "password": "a",
        }
        response = self.client.post(url, data=form_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Votre compte est relié à Inclusion Connect. Merci de vous connecter avec ce service."
        )


class SiaeStaffLoginTest(InclusionConnectBaseTestCase):
    def test_login_options(self):
        url = reverse("login:siae_staff")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "S'identifier avec Inclusion Connect")
        self.assertContains(response, reverse("inclusion_connect:authorize"))
        self.assertContains(response, "Adresse e-mail")
        self.assertContains(response, "Mot de passe")

    def test_login_using_django(self):
        user = SiaeStaffFactory()
        url = reverse("login:siae_staff")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

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
        self.assertEqual(response.status_code, 200)

        form_data = {
            "login": user.email,
            "password": "a",
        }
        response = self.client.post(url, data=form_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Votre compte est relié à Inclusion Connect. Merci de vous connecter avec ce service."
        )


class LaborInspectorLoginTest(TestCase):
    def test_login_options(self):
        url = reverse("login:labor_inspector")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "S'identifier avec Inclusion Connect")
        self.assertContains(response, "Adresse e-mail")
        self.assertContains(response, "Mot de passe")

    def test_login(self):
        user = LaborInspectorFactory()
        url = reverse("login:labor_inspector")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

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
        self.assertEqual(response.status_code, 200)

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
        UserFactory(email=FC_USERINFO["email"], identity_provider=IdentityProvider.DJANGO)
        UserFactory(
            username=FC_USERINFO["sub"],
            email="seconde@email.com",
            identity_provider=IdentityProvider.FRANCE_CONNECT,
        )

        # Temporary NIR is not stored with user information.
        response = mock_oauth_dance(self, expected_route="login:job_seeker")
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0].message,
            "Vous avez deux comptes sur la plateforme et nous detectons un conflit d'email : seconde@email.com "
            "et wossewodda-3728@yopmail.com.Veuillez vous rapprocher du support pour débloquer la situation "
            "en suivant <a href='https://communaute.inclusion.beta.gouv.fr/aide/emplois/#support'>ce lien</a>.",
        )
