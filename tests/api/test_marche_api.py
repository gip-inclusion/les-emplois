import datetime

from django.urls import reverse
from pytest_django.asserts import assertNumQueries
from rest_framework.test import APIClient

from itou.api.models import ServiceToken
from itou.companies.enums import COMPANY_KIND_RESERVED
from itou.companies.models import Company
from itou.nexus.enums import Service
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.utils.testing import BASE_NUM_QUERIES


NUM_QUERIES = BASE_NUM_QUERIES
NUM_QUERIES += 1  # count
NUM_QUERIES += 1  # get ServiceToken
NUM_QUERIES += 1  # get siaes
NUM_QUERIES += 1  # Prefetch members


class TestMarcheCompanyAPI:
    url = reverse("v1:marche-company-list")

    def api_client(self, service=Service.MARCHE):
        headers = {}
        if service is not None:
            token = ServiceToken.objects.create(service=service)
            headers = {"Authorization": f"Token {token.key}"}
        return APIClient(headers=headers)

    def test_list_companies_unauthenticated(self):
        api_client = self.api_client(service=None)
        response = api_client.get(self.url, format="json")
        assert response.status_code == 401

    def test_list_companies_unknown_token(self):
        api_client = self.api_client(service=None)
        response = api_client.get(self.url, format="json", HTTP_AUTHORIZATION="Token bad_token")
        assert response.status_code == 401

    def test_list_companies_token_from_other_service(self):
        api_client = self.api_client(service=Service.DATA_INCLUSION)
        response = api_client.get(self.url, format="json")
        assert response.status_code == 403

    def test_list_companies(self):
        api_client = self.api_client()
        company = CompanyFactory(siret="10000000000001", with_membership=True)

        with assertNumQueries(NUM_QUERIES):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200
        assert response.json()["results"] == [
            {
                "id": company.pk,
                "siret": company.siret,
                "naf": company.naf,
                "kind": company.kind,
                "name": company.name,
                "brand": company.brand,
                "phone": company.phone,
                "email": company.email,
                "website": company.website,
                "description": company.description,
                "address_line_1": company.address_line_1,
                "address_line_2": company.address_line_2,
                "post_code": company.post_code,
                "city": company.city,
                "department": company.department,
                "source": company.source,
                "latitude": company.latitude,
                "longitude": company.longitude,
                "convention_is_active": company.convention.is_active,
                "convention_asp_id": company.convention.asp_id,
                "admin_name": company.members.get().get_full_name(),
                "admin_email": company.members.get().email,
            }
        ]

    def test_list_companies_antenne_with_user_created_with_proper_siret(self, subtests):
        api_client = self.api_client()
        company_1 = CompanyFactory(siret="10000000000001")
        company_2 = CompanyFactory(siret="10000000000002", convention=company_1.convention)
        company_3 = CompanyFactory(
            siret="10000000000003", source=Company.SOURCE_USER_CREATED, convention=company_1.convention
        )

        with assertNumQueries(NUM_QUERIES):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200
        company_data_list = response.json()["results"]

        for company, siret in [
            (company_1, company_1.siret),
            (company_2, company_2.siret),
            (company_3, company_3.siret),
        ]:
            company_data = next(
                (company_data for company_data in company_data_list if company_data["id"] == company.pk),
                None,
            )
            with subtests.test(siret=company.siret):
                assert company_data is not None
                assert company_data["siret"] == siret

    def test_list_companies_antenne_with_user_created_and_999(self, subtests):
        api_client = self.api_client()
        company_1 = CompanyFactory(siret="10000000000001")
        company_2 = CompanyFactory(siret="10000000000002", source=Company.SOURCE_ASP, convention=company_1.convention)
        company_3 = CompanyFactory(
            siret="10000000099991", source=Company.SOURCE_USER_CREATED, convention=company_1.convention
        )

        num_queries = NUM_QUERIES
        num_queries += 1  # get parent siae
        with assertNumQueries(num_queries):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200

        company_data_list = response.json()["results"]

        for company, siret in [
            (company_1, company_1.siret),
            (company_2, company_2.siret),
            (company_3, company_1.siret),
        ]:
            company_data = next(
                (company_data for company_data in company_data_list if company_data["id"] == company.pk),
                None,
            )
            with subtests.test(siret=company.siret):
                assert company_data is not None
                assert company_data["siret"] == siret

    def test_list_companies_siret_with_999_and_no_other_siret_available(self):
        api_client = self.api_client()
        company = CompanyFactory(siret="10000000099991", source=Company.SOURCE_USER_CREATED)

        num_queries = NUM_QUERIES
        num_queries += 1  # get parent siae
        with assertNumQueries(num_queries):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200

        company_data_list = response.json()["results"]
        assert len(company_data_list) == 1

        assert company_data_list[0]["siret"] == company.siret[:9]  # fake nic is removed

    def test_list_companies_without_convention(self):
        api_client = self.api_client()
        CompanyFactory(convention=None)

        num_queries = NUM_QUERIES
        with assertNumQueries(num_queries):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200

        company_data_list = response.json()["results"]
        assert len(company_data_list) == 1

        assert company_data_list[0]["convention_is_active"] is None
        assert company_data_list[0]["convention_asp_id"] is None

    def test_list_companies_without_admins(self):
        api_client = self.api_client()
        company = CompanyFactory()
        # An active admin membership on a disabled user
        CompanyMembershipFactory(company=company, user__is_active=False, is_active=True, is_admin=True)
        # An inactive admin membership
        CompanyMembershipFactory(company=company, is_active=False, is_admin=True)
        # An active non-admin membership
        CompanyMembershipFactory(company=company, is_active=True, is_admin=False)

        num_queries = NUM_QUERIES
        with assertNumQueries(num_queries):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200

        company_data_list = response.json()["results"]
        assert len(company_data_list) == 1

        assert company_data_list[0]["admin_name"] is None
        assert company_data_list[0]["admin_email"] is None

    def test_list_companies_with_multiple_admins(self):
        api_client = self.api_client()
        company = CompanyFactory()
        CompanyMembershipFactory(company=company, joined_at=datetime.datetime(2021, 1, 1, tzinfo=datetime.UTC))
        latest_admin = CompanyMembershipFactory(
            company=company, joined_at=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC)
        ).user

        num_queries = NUM_QUERIES
        with assertNumQueries(num_queries):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200

        company_data_list = response.json()["results"]
        assert len(company_data_list) == 1

        assert company_data_list[0]["admin_name"] == latest_admin.get_full_name()
        assert company_data_list[0]["admin_email"] == latest_admin.email

    def test_list_no_reserved_companies(self):
        api_client = self.api_client()
        CompanyFactory(kind=COMPANY_KIND_RESERVED)

        num_queries = NUM_QUERIES
        num_queries -= 2  # no company and no prefetch memberships
        with assertNumQueries(num_queries):
            response = api_client.get(self.url, format="json")
        assert response.status_code == 200
        assert response.json() == {"count": 0, "next": None, "previous": None, "results": []}
