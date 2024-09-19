from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertNotContains

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.utils import constants as global_constants
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from tests.companies.factories import (
    CompanyFactory,
)


class TestCreateCompanyView:
    STRUCTURE_ALREADY_EXISTS_MSG = escape(
        "Le numéro de SIRET que vous avez renseigné est déjà utilisé par une structure ou une antenne,"
    )

    @staticmethod
    def siret_siren_error_msg(company):
        return escape(f"Le SIRET doit commencer par le SIREN {company.siren}")

    def test_create_non_preexisting_company_outside_of_siren_fails(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        client.force_login(user)

        url = reverse("companies_views:create_company")
        response = client.get(url)
        assert response.status_code == 200

        new_siren = "9876543210"
        new_siret = f"{new_siren}1234"
        assert company.siren != new_siren
        assert not Company.objects.filter(siret=new_siret).exists()

        post_data = {
            "siret": new_siret,
            "kind": company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = client.post(url, data=post_data)

        assertContains(response, self.siret_siren_error_msg(company))
        assertNotContains(response, self.STRUCTURE_ALREADY_EXISTS_MSG)

        assert not Company.objects.filter(siret=post_data["siret"]).exists()

    def test_create_preexisting_company_outside_of_siren_fails(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        client.force_login(user)

        url = reverse("companies_views:create_company")
        response = client.get(url)
        assert response.status_code == 200

        preexisting_company = CompanyFactory()
        new_siret = preexisting_company.siret
        assert company.siren != preexisting_company.siren
        assert Company.objects.filter(siret=new_siret).exists()

        post_data = {
            "siret": new_siret,
            "kind": preexisting_company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = client.post(url, data=post_data)

        assertNotContains(response, self.siret_siren_error_msg(company))
        assertContains(response, self.STRUCTURE_ALREADY_EXISTS_MSG)

        assert Company.objects.filter(siret=post_data["siret"]).count() == 1

    def test_cannot_create_company_with_same_siret_and_same_kind(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        client.force_login(user)

        url = reverse("companies_views:create_company")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {
            "siret": company.siret,
            "kind": company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = client.post(url, data=post_data)

        assertNotContains(response, self.siret_siren_error_msg(company))
        assertContains(response, self.STRUCTURE_ALREADY_EXISTS_MSG)
        assertContains(response, escape(global_constants.ITOU_HELP_CENTER_URL))

        assert Company.objects.filter(siret=post_data["siret"]).count() == 1

    def test_cannot_create_company_with_same_siret_and_different_kind(self, client, mocker):
        mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)

        company = CompanyFactory(with_membership=True)
        company.kind = CompanyKind.ETTI
        company.save()
        user = company.members.first()

        client.force_login(user)

        url = reverse("companies_views:create_company")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {
            "siret": company.siret,
            "kind": CompanyKind.ACI,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200

        assert Company.objects.filter(siret=post_data["siret"]).count() == 1

    def test_cannot_create_company_with_same_siren_and_different_kind(self, client, mocker):
        mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)

        company = CompanyFactory(with_membership=True)
        company.kind = CompanyKind.ETTI
        company.save()
        user = company.members.first()

        new_siret = company.siren + "12345"
        assert company.siret != new_siret

        client.force_login(user)

        url = reverse("companies_views:create_company")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {
            "siret": new_siret,
            "kind": CompanyKind.ACI,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200

        assert Company.objects.filter(siret=company.siret).count() == 1
        assert Company.objects.filter(siret=new_siret).count() == 0

    def test_create_company_with_same_siren_and_same_kind(self, client, mocker):
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )

        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        client.force_login(user)

        url = reverse("companies_views:create_company")
        response = client.get(url)
        assert response.status_code == 200

        new_siret = company.siren + "12345"
        assert company.siret != new_siret

        post_data = {
            "siret": new_siret,
            "kind": company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        mock_call_ban_geocoding_api.assert_called_once()

        new_company = Company.objects.get(siret=new_siret)
        assert new_company.has_admin(user)
        assert company.source == Company.SOURCE_ASP
        assert new_company.source == Company.SOURCE_USER_CREATED
        assert new_company.siret == post_data["siret"]
        assert new_company.kind == post_data["kind"]
        assert new_company.name == post_data["name"]
        assert new_company.address_line_1 == post_data["address_line_1"]
        assert new_company.city == post_data["city"]
        assert new_company.post_code == post_data["post_code"]
        assert new_company.department == post_data["department"]
        assert new_company.email == post_data["email"]
        assert new_company.phone == post_data["phone"]
        assert new_company.website == post_data["website"]
        assert new_company.description == post_data["description"]
        assert new_company.created_by == user
        assert new_company.source == Company.SOURCE_USER_CREATED
        assert new_company.is_active
        assert new_company.convention is not None
        assert company.convention == new_company.convention

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        assert new_company.coords == "SRID=4326;POINT (2.316754 48.838411)"
        assert new_company.latitude == 48.838411
        assert new_company.longitude == 2.316754
        assert new_company.geocoding_score == 0.5197687103594081
