from django.test import TestCase
from django.urls import reverse

from itou.users import enums as users_enums
from itou.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    SiaeStaffFactory,
)
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

    def test_redirect_to_new_login_views(self):
        # If an "account_type" URL parameter is present,
        # redirect to the correct login view.
        url = reverse("account_login") + "?account_type=siae"
        response = self.client.get(url)
        self.assertRedirects(response, reverse("login:siae_staff"), status_code=301)

        url = reverse("account_login") + "?account_type=prescriber"
        response = self.client.get(url)
        self.assertRedirects(response, reverse("login:prescriber"), status_code=301)

        url = reverse("account_login") + "?account_type=job_seeker"
        response = self.client.get(url)
        self.assertRedirects(response, reverse("login:job_seeker"), status_code=301)

        url = reverse("account_login") + "?account_type=labor_inspector"
        response = self.client.get(url)
        self.assertRedirects(response, reverse("login:labor_inspector"), status_code=301)

        # Wrong kind.
        url = reverse("account_login") + "?account_type=hater"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


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
        form = ItouLoginForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("FranceConnect", form.errors["__all__"][0])


class PrescriberLoginTest(TestCase):
    def test_login(self):
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


class SiaeStaffLoginTest(TestCase):
    def test_login(self):
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


class LaborInspectorLoginTest(TestCase):
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
