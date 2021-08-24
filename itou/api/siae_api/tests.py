from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.cities.factories import create_test_cities
from itou.users.factories import SiaeStaffFactory


ENDPOINT_URL = reverse("v1:siaes-list")


class SiaeAPIFetchListTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = SiaeStaffFactory()
        create_test_cities(["75"])

    def test_fetch_employee_record_list_without_params(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        response = self.client.get(ENDPOINT_URL, format="json")

        self.assertEquals(response.status_code, 400)

    def test_fetch_employee_record_list_with_too_high_distance(self):
        """
        The query parameter distance must be <= 100
        """
        query_params = {"code_insee": 75056, "distance_max_km": 200}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertContains(response, "distance_max_km doit être entre 0 et 100", status_code=400)

    def test_fetch_employee_record_list_with_negative_distance(self):
        """
        The query parameter distance must be positive
        """
        query_params = {"code_insee": 75056, "distance_max_km": -10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertContains(response, "distance_max_km doit être entre 0 et 100", status_code=400)

    def test_fetch_employee_record_list_with_invalid_code_insee(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        query_params = {"code_insee": 12345, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertEquals(response.content, b'{"detail":"Pas de ville avec pour code_insee 12345"}')
        self.assertEquals(response.status_code, 404)

    def test_fetch_employee_record_list(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        query_params = {"code_insee": 75056, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertEquals(response.status_code, 200)
