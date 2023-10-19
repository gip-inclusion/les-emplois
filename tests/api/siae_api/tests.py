import json

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.companies.enums import CompanyKind
from tests.cities.factories import create_city_guerande, create_city_saint_andre
from tests.companies.factories import SiaeFactory
from tests.users.factories import EmployerFactory
from tests.utils.test import BASE_NUM_QUERIES


ENDPOINT_URL = reverse("v1:siaes-list")


class SiaeAPIFetchListTest(APITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = EmployerFactory()

        # We create 2 cities and 2 siaes in Saint-Andre.
        self.saint_andre = create_city_saint_andre()
        self.guerande = create_city_guerande()
        self.siae_a = SiaeFactory(kind=CompanyKind.EI, department="44", coords=self.saint_andre.coords)
        self.siae_b = SiaeFactory(
            with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"), department="44", coords=self.saint_andre.coords
        )

    def test_performances(self):
        num_queries = BASE_NUM_QUERIES
        num_queries += 1  # Get city with insee_code
        num_queries += 1  # Count siaes
        num_queries += 1  # Select sias
        num_queries += 1  # prefetch job_description_through
        with self.assertNumQueries(num_queries):
            query_params = {"code_insee": self.saint_andre.code_insee, "distance_max_km": 100}
            self.client.get(ENDPOINT_URL, query_params, format="json")

    def test_fetch_siae_list_without_params(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        response = self.client.get(ENDPOINT_URL, format="json")

        self.assertContains(
            response, "Les paramètres `code_insee` et `distance_max_km` sont obligatoires.", status_code=400
        )

    def test_fetch_siae_list_with_too_high_distance(self):
        """
        The query parameter distance must be <= 100
        """
        query_params = {"code_insee": 44056, "distance_max_km": 200}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertContains(
            response, "Le paramètre `distance_max_km` doit être compris entre 0 et 100", status_code=400
        )

    def test_fetch_siae_list_with_negative_distance(self):
        """
        The query parameter distance must be positive
        """
        query_params = {"code_insee": 44056, "distance_max_km": -10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        self.assertContains(
            response, "Le paramètre `distance_max_km` doit être compris entre 0 et 100", status_code=400
        )

    def test_fetch_siae_list_with_invalid_code_insee(self):
        """
        The query parameters for INSEE code and distance are mandatories
        """
        query_params = {"code_insee": 12345, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        assert response.content == b'{"detail":"Pas de ville avec pour code_insee 12345"}'
        assert response.status_code == 404

    def test_fetch_siae_list(self):
        """
        Search for siaes in the city that has 2 SIAES
        """

        query_params = {"code_insee": self.saint_andre.code_insee, "distance_max_km": 100}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        body = json.loads(response.content)
        assert body["count"] == 2
        assert response.status_code == 200

    def test_fetch_siae_list_too_far(self):
        """
        Search for siaes in a city that has no SIAES
        """

        query_params = {"code_insee": self.guerande.code_insee, "distance_max_km": 10}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        body = json.loads(response.content)
        assert body["count"] == 0
        assert response.status_code == 200
