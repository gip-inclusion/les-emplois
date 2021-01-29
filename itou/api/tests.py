from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, SiaeStaffFactory


class SiaeAPITest(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_happy_path(self):
        siae1 = SiaeWithMembershipFactory()
        user = siae1.members.get()

        # Create a second siae that the user is not a member of to ensure it cannot be accessed.
        siae2 = SiaeFactory()
        self.assertFalse(siae2.has_member(user))

        url = reverse("api:token-auth")
        data = {"username": user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, 200)

        token = response.json()["token"]

        url = reverse("api:siaes")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()["count"], 1)  # Thus only siae1, not siae2.
        siae_json = response.json()["results"][0]
        self.assertEqual(siae_json["kind"], siae1.kind)
        self.assertEqual(siae_json["siret"], siae1.siret)
        self.assertEqual(siae_json["source"], siae1.source)

    def test_missing_token_breaks(self):
        url = reverse("api:siaes")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, 401)

    def test_incorrect_token_breaks(self):
        url = reverse("api:siaes")
        token = "you have to keep trying things in your life"
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, 401)

    def test_incorrect_password_breaks(self):
        user = SiaeStaffFactory()

        password = "not gonna work"
        url = reverse("api:token-auth")
        data = {"username": user.email, "password": password}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, 400)
