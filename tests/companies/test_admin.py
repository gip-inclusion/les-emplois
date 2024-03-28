from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from pytest_django.asserts import assertNumQueries

from itou.companies.models import Company
from tests.utils.test import parse_response_to_soup


class TestCompanyAdmin:
    def test_display_for_new_company(self, admin_client, snapshot):
        """Does not search approvals with company IS NULL"""
        # prewarm ContentType cache if needed to avoid extra query
        ContentType.objects.get_for_model(Company)
        with assertNumQueries(9):
            # 1. SELECT django session
            # 2. SELECT user
            # 3. SAVEPOINT
            # 4. SAVEPOINT
            # 5. RELEASE SAVEPOINT
            # 6. RELEASE SAVEPOINT
            # 7. SAVEPOINT
            # 8. UPDATE django session
            # 9. RELEASE SAVEPOINT
            response = admin_client.get(reverse("admin:companies_company_add"))
        response = parse_response_to_soup(response, selector=".field-approvals_list")
        assert str(response) == snapshot
