import pytest

from itou.companies.enums import CompanyKind
from itou.companies.perms import can_create_antenna
from tests.companies.factories import CompanyFactory


class TestCanCreateSiaeAntenna:
    def test_siae_admin_can_create_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=True)
        user = company.members.get()
        assert can_create_antenna(user, company, is_company_admin=True) is True

    def test_siae_normal_member_cannot_create_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=False)
        user = company.members.get()
        assert can_create_antenna(user, company, is_company_admin=False) is False

    def test_siae_admin_without_convention_cannot_create_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=True, convention=None)
        user = company.members.get()
        assert can_create_antenna(user, company, is_company_admin=True) is False

    @pytest.mark.parametrize("kind", CompanyKind)
    def test_admin_ability_to_create_antenna(self, kind):
        company = CompanyFactory(kind=kind, with_membership=True, membership__is_admin=True)
        user = company.members.get()
        expected = company.should_have_convention or company.kind == CompanyKind.GEIQ
        assert can_create_antenna(user, company, is_company_admin=True) is expected
