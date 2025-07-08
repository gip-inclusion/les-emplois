import pytest
from django.test import RequestFactory

from itou.companies.enums import CompanyKind
from itou.companies.perms import can_create_antenna
from itou.utils.perms.middleware import ItouCurrentOrganizationMiddleware
from tests.companies.factories import CompanyFactory


def run_perms_middleware(user):
    middleware = ItouCurrentOrganizationMiddleware(lambda x: x)
    rf = RequestFactory()
    fake_request = rf.get("/foo")
    fake_request.user = user
    fake_request.session = {}
    middleware(fake_request)
    return fake_request


class TestCanCreateSiaeAntenna:
    def test_siae_admin_can_create_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=True)
        user = company.members.get()
        request = run_perms_middleware(user)
        assert can_create_antenna(request) is True

    def test_siae_normal_member_cannot_create_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=False)
        user = company.members.get()
        request = run_perms_middleware(user)
        assert can_create_antenna(request) is False

    def test_siae_admin_without_convention_cannot_create_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=True, convention=None)
        user = company.members.get()
        request = run_perms_middleware(user)
        assert can_create_antenna(request) is False

    @pytest.mark.parametrize("kind", CompanyKind)
    def test_admin_ability_to_create_antenna(self, kind):
        company = CompanyFactory(kind=kind, with_membership=True, membership__is_admin=True)
        user = company.members.get()
        request = run_perms_middleware(user)
        expected = company.should_have_convention or company.kind == CompanyKind.GEIQ
        assert can_create_antenna(request) is expected
