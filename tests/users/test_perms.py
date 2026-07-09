import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.companies.perms import can_create_antenna
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import IdentityProvider
from itou.users.perms import can_orient_towards_insertion_service, can_register_mobilization_event
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
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


def make_anonymous():
    return AnonymousUser(), None


def make_jobseeker():
    return JobSeekerFactory(), None


def make_employer():
    membership = CompanyMembershipFactory()
    return membership.user, membership.company


def make_prescriber(**kwargs):
    membership = PrescriberMembershipFactory(**kwargs)
    return membership.user, membership.organization


def make_labor_inspector():
    membership = InstitutionMembershipFactory()
    return membership.user, membership.institution


def make_itou_staff():
    return ItouStaffFactory(), None


@pytest.mark.parametrize(
    "user_factory,expected",
    (
        pytest.param(make_jobseeker, False, id="job_seeker"),
        pytest.param(make_employer, True, id="employer"),
        pytest.param(
            lambda: make_prescriber(organization__authorized=False),
            True,
            id="orienteur",
        ),
        pytest.param(
            lambda: make_prescriber(organization__authorized=True),
            True,
            id="prescriber_authorized",
        ),
        pytest.param(
            lambda: make_prescriber(
                user__identity_provider=IdentityProvider.DJANGO,
                organization__authorized=True,
            ),
            True,
            id="prescriber_authorized_identity_provider_django",
        ),
        pytest.param(
            lambda: make_prescriber(
                organization__authorized=True,
                organization__siret=None,
            ),
            True,
            id="prescriber_authorized_no_siret",
        ),
        pytest.param(make_labor_inspector, False, id="labor_inspector"),
    ),
)
def test_can_orient_towards_insertion_service(user_factory, expected):
    request_factory = RequestFactory()
    request = request_factory.get("/")
    request.user, structure = user_factory()
    request.from_prescriber = False
    request.from_employer = False
    if structure:
        request.current_organization = structure
        if isinstance(structure, PrescriberOrganization):
            request.from_prescriber = True
        elif isinstance(structure, Company):
            request.from_employer = True
    assert can_orient_towards_insertion_service(request) is expected


@pytest.mark.parametrize(
    "user_factory,expected",
    (
        pytest.param(make_anonymous, True, id="anonymous"),
        pytest.param(make_jobseeker, False, id="job_seeker"),
        pytest.param(make_employer, True, id="employer"),
        pytest.param(
            lambda: make_prescriber(organization__authorized=False),
            True,
            id="orienteur",
        ),
        pytest.param(
            lambda: make_prescriber(organization__authorized=True),
            True,
            id="prescriber_authorized",
        ),
        pytest.param(
            lambda: make_prescriber(
                user__identity_provider=IdentityProvider.DJANGO,
                organization__authorized=True,
            ),
            True,
            id="prescriber_authorized_identity_provider_django",
        ),
        pytest.param(
            lambda: make_prescriber(
                organization__authorized=True,
                organization__siret=None,
            ),
            True,
            id="prescriber_authorized_no_siret",
        ),
        pytest.param(make_labor_inspector, False, id="labor_inspector"),
        pytest.param(make_itou_staff, False, id="itou_staff"),
    ),
)
def test_can_register_mobilization_event(user_factory, expected):
    request_factory = RequestFactory()
    request = request_factory.get("/")
    request.user, structure = user_factory()
    request.from_prescriber = False
    request.from_employer = False
    if structure:
        request.current_organization = structure
        if isinstance(structure, PrescriberOrganization):
            request.from_prescriber = True
        elif isinstance(structure, Company):
            request.from_employer = True
    assert can_register_mobilization_event(request) is expected
