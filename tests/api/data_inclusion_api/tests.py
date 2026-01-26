from django.urls import reverse
from pytest_django.asserts import assertNumQueries
from rest_framework.test import APIClient

from itou.api.models import ServiceToken
from itou.companies.enums import CompanyKind, CompanySource
from itou.nexus.enums import Service
from tests.api.utils import _str_with_tz
from tests.companies.factories import CompanyFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.utils.testing import BASE_NUM_QUERIES


NUM_QUERIES = BASE_NUM_QUERIES
NUM_QUERIES += 1  # count
NUM_QUERIES += 1  # get ServiceToken
NUM_QUERIES += 1  # get siae / organization

OLD_NUM_QUERIES = NUM_QUERIES - 1  # uses session Authentication, no token to fetch


class TestDataInclusionStructure:
    def test_list_missing_type_query_param(self):
        token = ServiceToken.objects.create(service=Service.DATA_INCLUSION)
        authenticated_client = APIClient(headers={"Authorization": f"Token {token.key}"})
        url = reverse("v1:structures-list")

        response = authenticated_client.get(url, format="json")
        assert response.status_code == 400


class TestDataInclusionSiaeStructure:
    url = reverse("v1:structures-list")

    def setup_method(self):
        self.token = ServiceToken.objects.create(service=Service.DATA_INCLUSION)
        self.authenticated_client = APIClient(headers={"Authorization": f"Token {self.token.key}"})

    def test_list_structures_unauthenticated(self, api_client):
        response = api_client.get(self.url, format="json", data={"type": "siae"})
        assert response.status_code == 401

    def test_list_structures_token_from_other_service(self):
        self.token.service = Service.DORA
        self.token.save()
        response = self.authenticated_client.get(self.url, format="json", data={"type": "siae"})
        assert response.status_code == 403

    def test_list_structures(self):
        company = CompanyFactory(siret="10000000000001")

        with assertNumQueries(NUM_QUERIES):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "siae"},
            )
        assert response.status_code == 200
        assert response.json()["results"] == [
            {
                "id": str(company.uid),
                "kind": company.kind,
                "nom": company.display_name,
                "siret": company.siret,
                "description": "",
                "site_web": company.website,
                "telephone": company.phone,
                "courriel": company.email,
                "code_postal": company.post_code,
                "commune": company.city,
                "adresse": company.address_line_1,
                "complement_adresse": company.address_line_2,
                "longitude": company.longitude,
                "latitude": company.latitude,
                "date_maj": _str_with_tz(company.updated_at),
                "lien_source": f"http://testserver{reverse('companies_views:card', kwargs={'siae_id': company.pk})}",
            }
        ]

    def test_list_structures_antenne_with_user_created_with_proper_siret(self, subtests):
        company_1 = CompanyFactory(siret="10000000000001", subject_to_iae_rules=True)
        company_2 = CompanyFactory(siret="10000000000002", subject_to_iae_rules=True, convention=company_1.convention)
        company_3 = CompanyFactory(
            siret="10000000000003",
            subject_to_iae_rules=True,
            source=CompanySource.USER_CREATED,
            convention=company_1.convention,
        )

        with assertNumQueries(NUM_QUERIES):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "siae"},
            )
            assert response.status_code == 200

        structure_data_list = response.json()["results"]

        for siae, siret, antenne in [
            (company_1, company_1.siret, False),
            (company_2, company_2.siret, False),
            # siae is user created, but it has its own siret
            # so it is not an antenne according to data.inclusion
            (company_3, company_3.siret, False),
        ]:
            structure_data = next(
                (structure_data for structure_data in structure_data_list if structure_data["id"] == str(siae.uid)),
                None,
            )
            with subtests.test(siret=siae.siret):
                assert structure_data is not None
                assert structure_data["siret"] == siret

    def test_list_structures_antenne_with_user_created_and_999(self, subtests):
        company_1 = CompanyFactory(siret="10000000000001", subject_to_iae_rules=True)
        company_2 = CompanyFactory(
            siret="10000000000002",
            subject_to_iae_rules=True,
            source=CompanySource.ASP,
            convention=company_1.convention,
        )
        company_3 = CompanyFactory(
            siret="10000000099991",
            subject_to_iae_rules=True,
            source=CompanySource.USER_CREATED,
            convention=company_1.convention,
        )

        num_queries = NUM_QUERIES
        num_queries += 1  # get parent siae
        with assertNumQueries(num_queries):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "siae"},
            )
        assert response.status_code == 200

        structure_data_list = response.json()["results"]

        for siae, siret, antenne in [
            (company_1, company_1.siret, False),
            (company_2, company_2.siret, False),
            # siret is replaced with parent siret
            (company_3, company_1.siret, True),
        ]:
            structure_data = next(
                (structure_data for structure_data in structure_data_list if structure_data["id"] == str(siae.uid)),
                None,
            )
            with subtests.test(siret=siae.siret):
                assert structure_data is not None
                assert structure_data["siret"] == siret

    def test_list_structures_siret_with_999_and_no_other_siret_available(self):
        CompanyFactory(siret="10000000099991", source=CompanySource.USER_CREATED)

        num_queries = NUM_QUERIES
        num_queries += 1  # get parent siae
        with assertNumQueries(num_queries):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "siae"},
            )
        assert response.status_code == 200

        structure_data_list = response.json()["results"]
        assert len(structure_data_list) == 1

        assert structure_data_list[0]["siret"] is None

    def test_list_structures_duplicated_siret(self, subtests):
        company_1 = CompanyFactory(siret="10000000000001", kind=CompanyKind.ACI)
        company_2 = CompanyFactory(siret=company_1.siret, kind=CompanyKind.EI)

        with assertNumQueries(NUM_QUERIES):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "siae"},
            )
        assert response.status_code == 200

        structure_data_list = response.json()["results"]

        for siae, siret, antenne in [
            # both structures will be marked as antennes, bc it is impossible to know
            # from data if one can be thought as an antenne of the other and if so, which
            # one is the antenne
            (company_1, company_1.siret, True),
            (company_2, company_2.siret, True),
        ]:
            structure_data = next(
                (structure_data for structure_data in structure_data_list if structure_data["id"] == str(siae.uid)),
                None,
            )
            with subtests.test(siret=siae.siret):
                assert structure_data is not None
                assert structure_data["siret"] == siret

    def test_list_structures_inactive_excluded(self):
        CompanyFactory(subject_to_iae_rules=True, convention__is_active=False)

        num_queries = NUM_QUERIES
        num_queries -= 1  # no siae to fetch
        with assertNumQueries(num_queries):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "siae"},
            )

        assert response.status_code == 200
        assert response.json()["results"] == []


class TestDataInclusionPrescriberStructure:
    url = reverse("v1:structures-list")

    def setup_method(self):
        self.token = ServiceToken.objects.create(service=Service.DATA_INCLUSION)
        self.authenticated_client = APIClient(headers={"Authorization": f"Token {self.token.key}"})

    def test_list_structures_unauthenticated(self, api_client):
        response = api_client.get(self.url, format="json", data={"type": "siae"})
        assert response.status_code == 401

    def test_list_structures_token_from_other_service(self):
        self.token.service = Service.DORA
        self.token.save()
        response = self.authenticated_client.get(self.url, format="json", data={"type": "siae"})
        assert response.status_code == 403

    def test_list_structures(self):
        orga = PrescriberOrganizationFactory(authorized=True)

        with assertNumQueries(NUM_QUERIES):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "orga"},
            )
        assert response.status_code == 200
        assert response.json()["results"] == [
            {
                "id": str(orga.uid),
                "kind": orga.kind,
                "nom": orga.name,
                "siret": orga.siret,
                "description": "",
                "site_web": orga.website,
                "telephone": orga.phone,
                "courriel": orga.email,
                "code_postal": orga.post_code,
                "commune": orga.city,
                "adresse": orga.address_line_1,
                "complement_adresse": orga.address_line_2,
                "longitude": orga.longitude,
                "latitude": orga.latitude,
                "date_maj": _str_with_tz(orga.updated_at),
                "lien_source": f"http://testserver{reverse('prescribers_views:card', kwargs={'org_id': orga.pk})}",
            }
        ]

    def test_list_structures_date_maj_value(self):
        orga = PrescriberOrganizationFactory()

        with assertNumQueries(NUM_QUERIES):
            response = self.authenticated_client.get(
                self.url,
                format="json",
                data={"type": "orga"},
            )

        assert response.status_code == 200
        structure_data = response.json()["results"][0]
        assert structure_data["date_maj"] == _str_with_tz(orga.updated_at)

        orga.description = "lorem ipsum"
        orga.save()

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "orga"},
        )
        assert response.status_code == 200
        structure_data = response.json()["results"][0]
        assert structure_data["date_maj"] == _str_with_tz(orga.updated_at)
