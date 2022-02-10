from django.test import TestCase
from django.urls import reverse

from itou.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    SiaeStaffFactory,
)


class ItouLoginTest(TestCase):
    def test_unauthorized_default_view(self):
        # ItouLogin overrides AllAuth default login view.
        # This parent class should be never be accessed directly.
        # Each child represents a login type (one per user kind).
        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)  # Forbidden

        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)  # Forbidden


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

        # Redirect to email confirmation.
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

        # Redirect to email confirmation.
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

        # Redirect to email confirmation.
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

        # Redirect to email confirmation.
        self.assertRedirects(response, reverse("account_email_verification_sent"))
