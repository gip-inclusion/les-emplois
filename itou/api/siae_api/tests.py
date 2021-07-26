from unittest import mock

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.cities.factories import create_test_cities
from itou.cities.models import City
from itou.employee_record.factories import EmployeeRecordWithProfileFactory
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithCompleteJobSeekerProfileFactory
from itou.users.factories import DEFAULT_PASSWORD, SiaeStaffFactory
from itou.utils.mocks.address_format import mock_get_geocoding_data


ENDPOINT_URL = reverse("v1:siaes-list")


class SiaeAPIFetchListTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = SiaeStaffFactory()
        create_test_cities(["75"])

    def authenticate(self):
        url = reverse("v1:token-auth")
        data = {"username": self.user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, 200)

        token = response.json()["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_fetch_employee_record_list_without_authentication(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        response = self.client.get(ENDPOINT_URL, format="json")

        self.assertEquals(response.status_code, 401)

    def test_fetch_employee_record_list_with_invalid_token(self):
        """
        The authentication token must be valid in order to perform the request
        """
        self.client.credentials(HTTP_AUTHORIZATION=f"Token some_invalid_token")
        query_params = {"code_insee": 75056, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertEquals(response.status_code, 401)

    def test_fetch_employee_record_list_without_params(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        self.authenticate()
        response = self.client.get(ENDPOINT_URL, format="json")

        self.assertEquals(response.status_code, 400)

    def test_fetch_employee_record_list_with_too_high_distance(self):
        """
        The query parameter distance must be <= 100
        """
        self.authenticate()
        query_params = {"code_insee": 75056, "distance_max_km": 200}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertContains(response, 'distance_max_km doit être entre 0 et 100', status_code=400)

    def test_fetch_employee_record_list_with_negative_distance(self):
        """
        The query parameter distance must be positive
        """
        self.authenticate()
        query_params = {"code_insee": 75056, "distance_max_km": -10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertContains(response, 'distance_max_km doit être entre 0 et 100', status_code=400)

    def test_fetch_employee_record_list_with_invalid_code_insee(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        self.authenticate()
        query_params = {"code_insee": 12345, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertEquals(response.content, b'{"detail":"Pas de ville avec pour code_insee 12345"}')
        self.assertEquals(response.status_code, 404)


    def test_fetch_employee_record_list(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        self.authenticate()
        query_params = {"code_insee": 75056, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertEquals(response.status_code, 200)
