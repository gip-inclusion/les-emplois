import json

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.companies.enums import CompanyKind, ContractType
from tests.cities.factories import create_city_guerande, create_city_saint_andre
from tests.companies.factories import CompanyFactory, JobDescriptionFactory
from tests.users.factories import EmployerFactory
from tests.utils.test import BASE_NUM_QUERIES

from ..utils import _str_with_tz


ENDPOINT_URL = reverse("v1:siaes-list")


class SiaeAPIFetchListTest(APITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = EmployerFactory()

        # We create 2 cities and 2 siaes in Saint-Andre.
        self.saint_andre = create_city_saint_andre()
        self.guerande = create_city_guerande()
        CompanyFactory(kind=CompanyKind.EI, department="44", coords=self.saint_andre.coords)
        CompanyFactory(
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

    def test_fetch_results(self):
        company = CompanyFactory(department="44", coords=self.guerande.coords, kind=CompanyKind.EI)
        job_1 = JobDescriptionFactory(
            company=company,
            location=None,
            open_positions=1,
            contract_type=ContractType.FIXED_TERM_I_PHC,
        )
        job_2 = JobDescriptionFactory(
            company=company,
            location=self.saint_andre,
            open_positions=3,
            contract_type="",
        )

        query_params = {"code_insee": self.guerande.code_insee, "distance_max_km": 1}
        response = self.client.get(ENDPOINT_URL, query_params, format="json")

        body = response.json()
        assert response.status_code == 200

        assert body["results"] == [
            {
                "cree_le": _str_with_tz(company.created_at),
                "mis_a_jour_le": _str_with_tz(company.updated_at),
                "siret": company.siret,
                "type": "EI",
                "raison_sociale": company.name,
                "enseigne": company.display_name,
                "site_web": company.website,
                "description": company.description,
                "bloque_candidatures": company.block_job_applications,
                "addresse_ligne_1": company.address_line_1,
                "addresse_ligne_2": company.address_line_2,
                "code_postal": company.post_code,
                "ville": company.city,
                "departement": company.department,
                "postes": [
                    {
                        "id": job_2.id,
                        "rome": str(job_2.appellation.rome),
                        "cree_le": _str_with_tz(job_2.created_at),
                        "mis_a_jour_le": _str_with_tz(job_2.updated_at),
                        "recrutement_ouvert": "True",
                        "description": job_2.description,
                        "appellation_modifiee": "",
                        "type_contrat": "",
                        "nombre_postes_ouverts": 3,
                        "lieu": {
                            "nom": self.saint_andre.name,
                            "departement": self.saint_andre.department,
                            "code_postaux": self.saint_andre.post_codes,
                            "code_insee": self.saint_andre.code_insee,
                        },
                        "profil_recherche": job_2.profile_description,
                    },
                    {
                        "id": job_1.id,
                        "rome": str(job_1.appellation.rome),
                        "cree_le": _str_with_tz(job_1.created_at),
                        "mis_a_jour_le": _str_with_tz(job_1.updated_at),
                        "recrutement_ouvert": "True",
                        "description": job_1.description,
                        "appellation_modifiee": "",
                        "type_contrat": "CDD-I PHC",
                        "nombre_postes_ouverts": 1,
                        "lieu": None,
                        "profil_recherche": job_1.profile_description,
                    },
                ],
            },
        ]

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

    def test_fetch_siae_list_rate_limits(self):
        query_params = {"code_insee": self.saint_andre.code_insee, "distance_max_km": 100}
        # Declared in itou.api.siae_api.viewsets.RestrictedUserRateThrottle.
        for _ in range(12):
            self.client.get(ENDPOINT_URL, query_params, format="json")
        response = self.client.get(ENDPOINT_URL, query_params, format="json")
        # Rate limited.
        assert response.status_code == 429
