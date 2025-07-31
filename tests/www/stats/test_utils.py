import pytest

from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.www.stats import utils
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import get_request


def test_can_view_stats_siae():
    company = CompanyFactory(with_membership=True)
    user = company.members.get()

    request = get_request(user)
    assert utils.can_view_stats_siae(request)

    # Even non admin members can view their SIAE stats.
    user.companymembership_set.update(is_admin=False)
    request = get_request(user)
    assert utils.can_view_stats_siae(request)


def test_can_view_stats_ft_as_regular_ft_agency():
    regular_fr_agency = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.FT, department="93"
    )
    user = regular_fr_agency.members.get()
    assert not regular_fr_agency.is_dtft
    assert not regular_fr_agency.is_drft
    assert not regular_fr_agency.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(regular_fr_agency) == ["93"]


def test_can_view_stats_ft_as_dtft_with_single_department():
    dtft_with_single_department = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.FT,
        code_safir_pole_emploi="49104",
        department="49",
    )
    user = dtft_with_single_department.members.get()
    assert dtft_with_single_department.is_dtft
    assert not dtft_with_single_department.is_drft
    assert not dtft_with_single_department.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(dtft_with_single_department) == ["49"]


def test_can_view_stats_ft_as_dtft_with_multiple_departments():
    dtft_with_multiple_departments = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.FT,
        code_safir_pole_emploi="72203",
        department="72",
    )
    user = dtft_with_multiple_departments.members.get()
    assert dtft_with_multiple_departments.is_dtft
    assert not dtft_with_multiple_departments.is_drft
    assert not dtft_with_multiple_departments.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(dtft_with_multiple_departments) == ["72", "53"]


def test_can_view_stats_ft_as_drft():
    drft = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.FT,
        department="93",
        code_safir_pole_emploi="75980",
    )
    user = drft.members.get()
    assert drft.is_drft
    assert not drft.is_dgft
    assert not drft.is_dtft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(drft) == [
        "75",
        "77",
        "78",
        "91",
        "92",
        "93",
        "94",
        "95",
    ]


def test_can_view_stats_ft_as_dgft():
    dgft = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.FT,
        department="93",
        code_safir_pole_emploi="00162",
    )
    user = dgft.members.get()
    assert not dgft.is_drft
    assert not dgft.is_dtft
    assert dgft.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(dgft)


@pytest.mark.parametrize(
    "kind",
    [
        PrescriberOrganizationKind.CAP_EMPLOI,
        PrescriberOrganizationKind.ML,
        PrescriberOrganizationKind.CHRS,
        PrescriberOrganizationKind.CHU,
        PrescriberOrganizationKind.OIL,
        PrescriberOrganizationKind.RS_FJT,
    ],
)
def can_view_stats_ph_whitelisted(kind):
    organization = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=kind,
    )
    request = get_request(organization.members.get())
    assert utils.can_view_stats_ph_whitelisted(request)


@pytest.mark.parametrize(
    "kind, is_admin, expected_can_view_stats_ddets_iae",
    [
        # Admin member of DDETS IAE can access.
        (InstitutionKind.DDETS_IAE, True, True),
        # Non admin member of DDETS IAE can access as well.
        (InstitutionKind.DDETS_IAE, False, True),
        # Member of institution of wrong kind cannot access.
        (InstitutionKind.OTHER, True, False),
    ],
)
def test_can_view_stats_ddets_iae(kind, is_admin, expected_can_view_stats_ddets_iae):
    institution = InstitutionWithMembershipFactory(kind=kind, membership__is_admin=is_admin, department="93")
    request = get_request(institution.members.get())
    assert utils.can_view_stats_ddets_iae(request) is expected_can_view_stats_ddets_iae
    assert utils.can_view_stats_dashboard_widget(request)


def test_can_view_stats_dreets_iae():
    # Admin member of DREETS IAE can access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DREETS_IAE, department="93")
    request = get_request(institution.members.get())
    assert utils.can_view_stats_dreets_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin member of DREETS IAE can access as well.
    institution = InstitutionWithMembershipFactory(
        kind=InstitutionKind.DREETS_IAE, membership__is_admin=False, department="93"
    )
    request = get_request(institution.members.get())
    assert utils.can_view_stats_dreets_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Member of institution of wrong kind cannot access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
    request = get_request(institution.members.get())
    assert not utils.can_view_stats_dreets_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)


def test_can_view_stats_dgefp_iae():
    # Admin member of DGEFP can access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DGEFP_IAE, department="93")
    request = get_request(institution.members.get())
    assert utils.can_view_stats_dgefp_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin member of DGEFP can access as well.
    institution = InstitutionWithMembershipFactory(
        kind=InstitutionKind.DGEFP_IAE, membership__is_admin=False, department="93"
    )
    request = get_request(institution.members.get())
    assert utils.can_view_stats_dgefp_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Member of institution of wrong kind cannot access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
    request = get_request(institution.members.get())
    assert not utils.can_view_stats_dgefp_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)


def test_can_view_stats_staff():
    for user in [
        EmployerFactory(with_company=True),
        PrescriberFactory(),
        LaborInspectorFactory(membership=True),
        JobSeekerFactory(),
    ]:
        request = get_request(user)
        assert request.user.is_authenticated
        assert not utils.can_view_stats_staff(request)

    user = ItouStaffFactory()
    user.is_verified = lambda: True  # Fake django_otp.middleware.OTPMiddleware
    assert utils.can_view_stats_staff(get_request(user))
