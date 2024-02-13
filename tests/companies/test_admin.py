from django.urls import reverse
from pytest_django.asserts import assertNumQueries

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
