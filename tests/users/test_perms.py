import pytest

from itou.companies.enums import CompanyKind
from itou.companies.perms import can_create_antenna
from tests.companies.factories import CompanyFactory
from tests.utils.testing import get_request


class TestCanCreateSiaeAntenna:
    @pytest.mark.parametrize("admin", [True, False])
    def test_can_create_antenna(self, admin):
        company = CompanyFactory(with_membership=True, membership__is_admin=admin, subject_to_iae_rules=True)
        user = company.members.get()
        request = get_request(user)
        assert can_create_antenna(request) is admin

    def test_siae_admin_without_convention_cannot_create_antenna(self):
        company = CompanyFactory(
            with_membership=True, membership__is_admin=True, convention=None, subject_to_iae_rules=True
        )
        user = company.members.get()
        request = get_request(user)
        assert can_create_antenna(request) is False

    @pytest.mark.parametrize("kind", CompanyKind)
    def test_admin_ability_to_create_antenna(self, kind):
        company = CompanyFactory(kind=kind, with_membership=True, membership__is_admin=True)
        user = company.members.get()
        request = get_request(user)
        expected = company.should_have_convention or company.kind == CompanyKind.GEIQ
        assert can_create_antenna(request) is expected
