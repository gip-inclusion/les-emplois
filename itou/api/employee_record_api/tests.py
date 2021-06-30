from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.job_applications.factories import JobApplicationFactory
from itou.users.factories import DEFAULT_PASSWORD, SiaeStaffFactory


class DummyEmployeeRecordAPITest(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_happy_path(self):
        user = SiaeStaffFactory()
        # Create enough fake job applications so that the dummy endpoint returns the first 25 of them.
        JobApplicationFactory.create_batch(30)

        url = reverse("api:token-auth")
        data = {"username": user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, 200)

        token = response.json()["token"]

        url = reverse("api:dummy-employee-records")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, 200)

        # The dummy endpoint always returns 25 records, first page is 20 of them.
        self.assertEqual(response.json()["count"], 25)
        self.assertEqual(len(response.json()["results"]), 20)

        employee_record_json = response.json()["results"][0]
        self.assertIn("mesure", employee_record_json)
        self.assertIn("siret", employee_record_json)
        self.assertIn("numeroAnnexe", employee_record_json)
        self.assertIn("personnePhysique", employee_record_json)
        self.assertIn("passIae", employee_record_json["personnePhysique"])
        self.assertIn("adresse", employee_record_json)
        self.assertIn("situationSalarie", employee_record_json)
