from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, override_settings

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


@override_settings(STATS_CD_DEPARTMENT_WHITELIST=["93"])
def test_can_view_stats_cd():
    """
    CD as in "Conseil Départemental".
    """
    # Department outside of the whitelist cannot access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.DEPT, department="01"
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Admin prescriber of authorized CD can access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.DEPT, department="93"
    )
    request = get_request(org.members.get())
    assert utils.can_view_stats_cd(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin prescriber can access as well.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.DEPT,
        membership__is_admin=False,
        department="93",
    )
    request = get_request(org.members.get())
    assert utils.can_view_stats_cd(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non authorized organization does not give access.
    org = PrescriberOrganizationWithMembershipFactory(
        kind=PrescriberOrganizationKind.DEPT,
        department="93",
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non CD organization does not give access.
    org = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.CHRS,
        department="93",
    )
    request = get_request(org.members.get())
    assert not utils.can_view_stats_cd(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Prescriber without organization cannot access.
    request = get_request(PrescriberFactory())
    assert not utils.can_view_stats_cd(request)
    assert utils.can_view_stats_dashboard_widget(request)


def test_can_view_stats_pe_as_regular_pe_agency():
    regular_pe_agency = PrescriberOrganizationWithMembershipFactory(
        authorized=True, kind=PrescriberOrganizationKind.PE, department="93"
    )
    user = regular_pe_agency.members.get()
    assert not regular_pe_agency.is_dtpe
    assert not regular_pe_agency.is_drpe
    assert not regular_pe_agency.is_dgpe
    request = get_request(user)
    assert utils.can_view_stats_pe(request)
    assert utils.get_stats_pe_departments(request) == ["93"]


def test_can_view_stats_pe_as_dtpe_with_single_department():
    dtpe_with_single_department = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        code_safir_pole_emploi="49104",
        department="49",
    )
    user = dtpe_with_single_department.members.get()
    assert dtpe_with_single_department.is_dtpe
    assert not dtpe_with_single_department.is_drpe
    assert not dtpe_with_single_department.is_dgpe
    request = get_request(user)
    assert utils.can_view_stats_pe(request)
    assert utils.get_stats_pe_departments(request) == ["49"]


def test_can_view_stats_pe_as_dtpe_with_multiple_departments():
    dtpe_with_multiple_departments = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        code_safir_pole_emploi="72203",
        department="72",
    )
    user = dtpe_with_multiple_departments.members.get()
    assert dtpe_with_multiple_departments.is_dtpe
    assert not dtpe_with_multiple_departments.is_drpe
    assert not dtpe_with_multiple_departments.is_dgpe
    request = get_request(user)
    assert utils.can_view_stats_pe(request)
    assert utils.get_stats_pe_departments(request) == ["72", "53"]


def test_can_view_stats_pe_as_drpe():
    drpe = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        department="93",
        code_safir_pole_emploi="75980",
    )
    user = drpe.members.get()
    assert drpe.is_drpe
    assert not drpe.is_dgpe
    assert not drpe.is_dtpe
    request = get_request(user)
    assert utils.can_view_stats_pe(request)
    assert utils.get_stats_pe_departments(request) == [
        "75",
        "77",
        "78",
        "91",
        "92",
        "93",
        "94",
        "95",
    ]


def test_can_view_stats_pe_as_dgpe():
    dgpe = PrescriberOrganizationWithMembershipFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.PE,
        department="93",
        code_safir_pole_emploi="00162",
    )
    user = dgpe.members.get()
    assert not dgpe.is_drpe
    assert not dgpe.is_dtpe
    assert dgpe.is_dgpe
    request = get_request(user)
    assert utils.can_view_stats_pe(request)
    assert utils.get_stats_pe_departments(request)


def test_can_view_stats_ddets_iae():
    # Admin member of DDETS IAE can access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DDETS_IAE, department="93")
    request = get_request(institution.members.get())
    assert utils.can_view_stats_ddets_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin member of DDETS IAE can access as well.
    institution = InstitutionWithMembershipFactory(
        kind=InstitutionKind.DDETS_IAE, membership__is_admin=False, department="93"
    )
    request = get_request(institution.members.get())
    assert utils.can_view_stats_ddets_iae(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Member of institution of wrong kind cannot access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
    request = get_request(institution.members.get())
    assert not utils.can_view_stats_ddets_iae(request)
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


def test_can_view_stats_dgefp():
    # Admin member of DGEFP can access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DGEFP, department="93")
    request = get_request(institution.members.get())
    assert utils.can_view_stats_dgefp(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Non admin member of DGEFP can access as well.
    institution = InstitutionWithMembershipFactory(
        kind=InstitutionKind.DGEFP, membership__is_admin=False, department="93"
    )
    request = get_request(institution.members.get())
    assert utils.can_view_stats_dgefp(request)
    assert utils.can_view_stats_dashboard_widget(request)

    # Member of institution of wrong kind cannot access.
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
    request = get_request(institution.members.get())
    assert not utils.can_view_stats_dgefp(request)
    assert utils.can_view_stats_dashboard_widget(request)
