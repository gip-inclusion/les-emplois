from django.urls import reverse

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from tests.companies.factories import (
    CompanyFactory,
    SiaeConventionFactory,
)
from tests.users.factories import EmployerFactory


class TestShowAndSelectFinancialAnnex:
    def test_asp_source_siae_admin_can_see_but_cannot_select_af(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_ASP

        client.force_login(user)
        url = reverse("dashboard:index")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:select_financial_annex")
        response = client.get(url)
        assert response.status_code == 403

    def test_user_created_siae_admin_can_see_and_select_af(self, client):
        company = CompanyFactory(
            source=Company.SOURCE_USER_CREATED,
            with_membership=True,
        )
        user = company.members.first()
        old_convention = company.convention
        # Only conventions of the same SIREN can be selected.
        new_convention = SiaeConventionFactory(siret_signature=f"{company.siren}12345")

        assert company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_USER_CREATED

        client.force_login(user)
        url = reverse("dashboard:index")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:select_financial_annex")
        response = client.get(url)
        assert response.status_code == 200

        assert company.convention == old_convention
        assert company.convention != new_convention

        post_data = {
            "financial_annexes": new_convention.financial_annexes.get().id,
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        company.refresh_from_db()
        assert company.convention != old_convention
        assert company.convention == new_convention

    def test_staff_created_siae_admin_cannot_see_nor_select_af(self, client):
        company = CompanyFactory(source=Company.SOURCE_STAFF_CREATED, with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_STAFF_CREATED

        client.force_login(user)
        url = reverse("dashboard:index")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = client.get(url)
        assert response.status_code == 403

    def test_asp_source_siae_non_admin_cannot_see_nor_select_af(self, client):
        company = CompanyFactory(with_membership=True)
        user = EmployerFactory()
        company.members.add(user)
        assert not company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_ASP

        client.force_login(user)
        url = reverse("dashboard:index")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = client.get(url)
        assert response.status_code == 403

    def test_import_created_geiq_admin_cannot_see_nor_select_af(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, source=Company.SOURCE_GEIQ, with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert not company.should_have_convention
        assert company.source == Company.SOURCE_GEIQ

        client.force_login(user)
        url = reverse("dashboard:index")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = client.get(url)
        assert response.status_code == 403

    def test_user_created_geiq_admin_cannot_see_nor_select_af(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, source=Company.SOURCE_USER_CREATED, with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert not company.should_have_convention
        assert company.source == Company.SOURCE_USER_CREATED

        client.force_login(user)
        url = reverse("dashboard:index")
        response = client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = client.get(url)
        assert response.status_code == 403
