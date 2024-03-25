from django.urls import reverse
from pytest_django.asserts import assertContains, assertNumQueries, assertRedirects

from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.companies.factories import CompanyFactory
from tests.users.factories import EmployerFactory
from tests.utils.test import parse_response_to_soup


class TestCompanyAdmin:
    def test_display_for_new_company(self, admin_client, snapshot):
        """Does not search approvals with company IS NULL"""
        # 1. SELECT django session
        # 2. SELECT user
        # 3. SAVEPOINT
        # 4. SAVEPOINT
        # 5. SELECT content type for companies
        # 6. RELEASE SAVEPOINT
        # 7. RELEASE SAVEPOINT
        # 8. SAVEPOINT
        # 9. UPDATE django session
        # 10. RELEASE SAVEPOINT
        with assertNumQueries(10):
            response = admin_client.get(reverse("admin:companies_company_add"))
        response = parse_response_to_soup(response, selector=".field-approvals_list")
        assert str(response) == snapshot

    def test_deactivate_last_admin(self, admin_client):
        company = CompanyFactory(with_membership=True)
        membership = company.memberships.first()
        assert membership.is_admin

        change_url = reverse("admin:companies_company_change", args=[company.pk])
        response = admin_client.get(change_url)
        assert response.status_code == 200

        response = admin_client.post(
            change_url,
            data={
                "id": company.id,
                "siret": company.siret,
                "kind": company.kind.value,
                "name": company.name,
                "phone": company.phone,
                "email": company.email,
                "companymembership_set-TOTAL_FORMS": "2",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                # companymembership_pet-0-is_admin is absent
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)
        assertContains(
            response,
            (
                "Vous venez de supprimer le dernier administrateur de la structure. "
                "Les membres restants risquent de solliciter le support."
            ),
        )

        assert_set_admin_role__removal(membership.user, company)

    def test_delete_admin(self, admin_client):
        company = CompanyFactory(with_membership=True)
        membership = company.memberships.first()
        assert membership.is_admin

        change_url = reverse("admin:companies_company_change", args=[company.pk])
        response = admin_client.get(change_url)
        assert response.status_code == 200

        response = admin_client.post(
            change_url,
            data={
                "id": company.id,
                "siret": company.siret,
                "kind": company.kind.value,
                "name": company.name,
                "phone": company.phone,
                "email": company.email,
                "companymembership_set-TOTAL_FORMS": "2",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                "companymembership_set-0-is_admin": "on",
                "companymembership_set-0-DELETE": "on",
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)

        assert_set_admin_role__removal(membership.user, company)

    def test_add_admin(self, admin_client):
        company = CompanyFactory(with_membership=True)
        membership = company.memberships.first()
        employer = EmployerFactory()
        assert membership.is_admin

        change_url = reverse("admin:companies_company_change", args=[company.pk])
        response = admin_client.get(change_url)
        assert response.status_code == 200

        response = admin_client.post(
            change_url,
            data={
                "id": company.id,
                "siret": company.siret,
                "kind": company.kind.value,
                "name": company.name,
                "phone": company.phone,
                "email": company.email,
                "companymembership_set-TOTAL_FORMS": "2",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                "companymembership_set-0-is_admin": "on",
                "companymembership_set-1-company": company.pk,
                "companymembership_set-1-user": employer.pk,
                "companymembership_set-1-is_admin": "on",
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)

        assert_set_admin_role__creation(employer, company)
