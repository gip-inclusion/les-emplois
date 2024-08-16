import factory.fuzzy
import pytest
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, override_settings

from itou.common_apps.address.departments import DEPARTMENTS, REGIONS
from itou.companies.enums import CompanyKind
from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.perms.middleware import ItouCurrentOrganizationMiddleware
from itou.www.stats import utils
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import (
    PrescriberFactory,
)
from tests.utils.tests import get_response_for_middlewaremixin


def get_request(user):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user
    SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
    MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
    ItouCurrentOrganizationMiddleware(get_response_for_middlewaremixin)(request)
    return request


def test_can_view_stats_siae():
    company = CompanyFactory(with_membership=True)
    user = company.members.get()

    request = get_request(user)
    assert utils.can_view_stats_siae(request)

    # Even non admin members can view their SIAE stats.
    user.companymembership_set.update(is_admin=False)
    request = get_request(user)
    assert utils.can_view_stats_siae(request)


def test_can_view_stats_siae_aci():
    company = CompanyFactory(
        kind=CompanyKind.ACI, department=factory.fuzzy.FuzzyChoice([31, 84]), with_membership=True
    )
    user = company.members.get()

    request = get_request(user)
    assert utils.can_view_stats_siae_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Even non admin members can view their SIAE stats.
    user.companymembership_set.update(is_admin=False)
    request = get_request(user)
    assert utils.can_view_stats_siae_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)


@override_settings(STATS_CD_DEPARTMENT_WHITELIST=["93"])
def test_can_view_stats_cd_whitelist():
    """
    CD as in "Conseil Départemental".
    """
    # Department outside of the whitelist cannot access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.DEPT, department="01"
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd_whitelist(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Admin prescriber of authorized CD can access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.DEPT, department="93"
    )
    request = get_request(org.members.get())
    assert utils.can_view_stats_cd_whitelist(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin prescriber can access as well.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.DEPT,
        membership__is_admin=False,
        department="93",
    )
    request = get_request(org.members.get())
    assert utils.can_view_stats_cd_whitelist(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non authorized organization does not give access.
    org = PrescriberOrganizationWithMembershipFactory(
        kind=PrescriberOrganizationKind.DEPT,
        department="93",
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd_whitelist(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non CD organization does not give access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.CHRS,
        department="93",
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd_whitelist(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Prescriber without organization cannot access.
    request = get_request(PrescriberFactory())
    assert not utils.can_view_stats_cd_whitelist(request)
    assert utils.can_view_stats_dashboard_widget(request)


def test_can_view_stats_cd_aci(settings):
    """
    CD as in "Conseil Départemental".
    """
    # Department outside of the whitelist cannot access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.DEPT,
        department=factory.fuzzy.FuzzyChoice(set(DEPARTMENTS) - set(settings.STATS_ACI_DEPARTMENT_WHITELIST)),
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Admin prescriber of authorized CD can access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.DEPT, department=factory.fuzzy.FuzzyChoice([31, 84])
    )
    request = get_request(org.members.get())
    assert utils.can_view_stats_cd_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin prescriber can access as well.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.DEPT,
        membership__is_admin=False,
        department=factory.fuzzy.FuzzyChoice([31, 84]),
    )
    request = get_request(org.members.get())
    assert utils.can_view_stats_cd_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non authorized organization does not give access.
    org = PrescriberOrganizationWithMembershipFactory(
        kind=PrescriberOrganizationKind.DEPT,
        department=factory.fuzzy.FuzzyChoice([31, 84]),
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non CD organization does not give access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.CHRS,
        department=factory.fuzzy.FuzzyChoice([31, 84]),
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Prescriber without organization cannot access.
    request = get_request(PrescriberFactory())
    assert not utils.can_view_stats_cd_aci(request)
    assert utils.can_view_stats_dashboard_widget(request)


def test_can_view_stats_ft_as_regular_pe_agency():
    regular_pe_agency = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.PE, department="93"
    )
    user = regular_pe_agency.members.get()
    assert not regular_pe_agency.is_dtft
    assert not regular_pe_agency.is_drft
    assert not regular_pe_agency.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(request) == ["93"]


def test_can_view_stats_ft_as_dtft_with_single_department():
    dtft_with_single_department = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        code_safir_pole_emploi="49104",
        department="49",
    )
    user = dtft_with_single_department.members.get()
    assert dtft_with_single_department.is_dtft
    assert not dtft_with_single_department.is_drft
    assert not dtft_with_single_department.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(request) == ["49"]


def test_can_view_stats_ft_as_dtft_with_multiple_departments():
    dtft_with_multiple_departments = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        code_safir_pole_emploi="72203",
        department="72",
    )
    user = dtft_with_multiple_departments.members.get()
    assert dtft_with_multiple_departments.is_dtft
    assert not dtft_with_multiple_departments.is_drft
    assert not dtft_with_multiple_departments.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(request) == ["72", "53"]


def test_can_view_stats_ft_as_drft():
    drft = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        department="93",
        code_safir_pole_emploi="75980",
    )
    user = drft.members.get()
    assert drft.is_drft
    assert not drft.is_dgft
    assert not drft.is_dtft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(request) == [
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
        kind=PrescriberOrganizationKind.PE,
        department="93",
        code_safir_pole_emploi="00162",
    )
    user = dgft.members.get()
    assert not dgft.is_drft
    assert not dgft.is_dtft
    assert dgft.is_dgft
    request = get_request(user)
    assert utils.can_view_stats_ft(request)
    assert utils.get_stats_ft_departments(request)


@pytest.mark.parametrize(
    "kind",
    [
        PrescriberOrganizationKind.CHRS,
        PrescriberOrganizationKind.CHU,
        PrescriberOrganizationKind.OIL,
        PrescriberOrganizationKind.RS_FJT,
    ],
)
@pytest.mark.parametrize("region", ["Île-de-France", "Auvergne-Rhône-Alpes", "Nouvelle-Aquitaine"])
def test_can_view_stats_ph_limited_access_organization_kind_whitelist(kind, region):
    organization = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=kind,
        department=factory.fuzzy.FuzzyChoice(REGIONS[region]),
    )
    request = get_request(organization.members.get())
    assert utils.can_view_stats_ph(request)


@pytest.mark.parametrize(
    "kind",
    [
        PrescriberOrganizationKind.CAP_EMPLOI,
        PrescriberOrganizationKind.ML,
    ],
)
def test_can_view_stats_ph_full_access_organization_kind_whitelist(kind):
    organization = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=kind,
    )
    request = get_request(organization.members.get())
    assert utils.can_view_stats_ph(request)


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


@pytest.mark.parametrize(
    "kind, is_admin, expected_can_view_stats_ddets_iae_aci",
    [
        # Admin member of DDETS IAE can access.
        (InstitutionKind.DDETS_IAE, True, True),
        # Non admin member of DDETS IAE can access as well.
        (InstitutionKind.DDETS_IAE, False, True),
        # Member of institution of wrong kind cannot access.
        (InstitutionKind.OTHER, True, False),
    ],
)
def test_can_view_stats_ddets_iae_aci(kind, is_admin, expected_can_view_stats_ddets_iae_aci):
    # Admin member of DDETS IAE can access.
    institution = InstitutionWithMembershipFactory(
        kind=kind, membership__is_admin=is_admin, department=factory.fuzzy.FuzzyChoice([31, 84])
    )
    request = get_request(institution.members.get())
    assert utils.can_view_stats_ddets_iae_aci(request) is expected_can_view_stats_ddets_iae_aci
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
