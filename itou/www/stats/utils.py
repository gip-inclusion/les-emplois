from django.conf import settings
from django.core.exceptions import PermissionDenied

from itou.common_apps.address.departments import DEPARTMENTS, REGIONS
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.prescribers.enums import (DTPE_SAFIR_CODE_TO_DEPARTMENTS,
                                    PrescriberAuthorizationStatus,
                                    PrescriberOrganizationKind)
from itou.prescribers.models import PrescriberOrganization


def can_view_stats_dashboard_widget(request):
    """
    Whether a stats section should be displayed on the user's dashboard.

    It should be displayed to all professional users, even when no specific can_view_stats_* condition
    is available to them.
    """
    return request.user.is_employer or request.user.is_prescriber or request.user.is_labor_inspector


def can_view_stats_siae(request):
    """
    General access rights for most SIAE stats.
    Users of a SIAE can view their SIAE data and only theirs.
    """
    return (
        request.user.is_employer
        and isinstance(request.current_organization, Company)
        # Metabase expects a filter on the SIAE ASP id (technically `siae.convention.asp_id`) which is why
        # we require a convention object to exist here.
        # Some SIAE don't have a convention (SIAE created by support, GEIQ, EA...).
        and request.current_organization.convention is not None
    )


def can_view_stats_siae_aci(request):
    """
    Non official stats with very specific access rights.
    """
    return (
        can_view_stats_siae(request)
        and request.current_organization.kind == CompanyKind.ACI
        and request.current_organization.department in settings.STATS_ACI_DEPARTMENT_WHITELIST
    )


def can_view_stats_siae_etp(request):
    """
    Non official stats with very specific access rights.
    """
    return (
        can_view_stats_siae(request)
        and request.is_current_organization_admin
        and request.user.pk in settings.STATS_SIAE_USER_PK_WHITELIST
    )


def can_view_stats_siae_orga_etp(request):
    """
    Non official stats with very specific access rights.
    """
    return can_view_stats_siae(request) and request.current_organization.pk in settings.STATS_SIAE_PK_WHITELIST


def can_view_stats_siae_hiring_report(request):
    return can_view_stats_siae(request)


def can_view_stats_cd(request):
    """
    Users of a real CD can view the confidential CD stats for their department only.

    CD as in "Conseil Départemental".

    Unfortunately the `PrescriberOrganizationKind.DEPT` kind contains not only the real CD but also some random
    organizations authorized by some CD.
    When such a random non-CD org is registered, it is not authorized yet, thus will be filtered out correctly.
    Later, our staff will authorize the random non-CD org, flag it as `is_brsa` and change its kind to `OTHER`.
    Sometimes our staff makes human errors and forgets to flag it as `is_brsa` or to change its kind.
    Hence we take extra precautions to filter out these edge cases to ensure we never ever show sensitive stats to
    a non-CD organization of the `DEPT` kind.
    """
    return (
        request.user.is_prescriber
        and isinstance(request.current_organization, PrescriberOrganization)
        and request.current_organization.kind == PrescriberOrganizationKind.DEPT
        and request.current_organization.is_authorized
        and request.current_organization.authorization_status == PrescriberAuthorizationStatus.VALIDATED
        and not request.current_organization.is_brsa
    )


def can_view_stats_cd_whitelist(request):
    return (
        can_view_stats_cd(request)
        and request.current_organization.department in settings.STATS_CD_DEPARTMENT_WHITELIST
    )


def can_view_stats_cd_aci(request):
    return (
        can_view_stats_cd(request)
        and request.current_organization.department in settings.STATS_ACI_DEPARTMENT_WHITELIST
    )


def can_view_stats_pe(request):
    return (
        request.user.is_prescriber
        and isinstance(request.current_organization, PrescriberOrganization)
        and request.current_organization.kind == PrescriberOrganizationKind.PE
        and request.current_organization.is_authorized
        and request.current_organization.authorization_status == PrescriberAuthorizationStatus.VALIDATED
    )


def can_view_stats_ph(request):
    organization_kind_whitelist = [
        PrescriberOrganizationKind.CHRS,
        PrescriberOrganizationKind.CHU,
        PrescriberOrganizationKind.CAP_EMPLOI,
        PrescriberOrganizationKind.ML,
        PrescriberOrganizationKind.OIL,
        PrescriberOrganizationKind.RS_FJT,
    ]
    return (
        request.user.is_prescriber
        and isinstance(request.current_organization, PrescriberOrganization)
        and request.current_organization.kind in organization_kind_whitelist
        and request.current_organization.is_authorized
        and request.current_organization.authorization_status == PrescriberAuthorizationStatus.VALIDATED
        and request.current_organization.region in ["Île-de-France", "Auvergne-Rhône-Alpes", "Nouvelle-Aquitaine"]
    )


def can_view_stats_ddets_iae(request):
    """
    Users of a DDETS IAE can view the confidential DDETS IAE stats of their department only.
    """
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DDETS_IAE
    )


def can_view_stats_ddets_iae_aci(request):
    """
    Users of a DDETS IAE can view the confidential DDETS IAE stats of their department only.
    """
    return (
        can_view_stats_ddets_iae(request)
        and request.current_organization.department in settings.STATS_ACI_DEPARTMENT_WHITELIST
    )


def can_view_stats_ddets_iae_ph_prescription(request):
    return (
        can_view_stats_ddets_iae(request)
        and request.current_organization.region in settings.STATS_PH_PRESCRIPTION_REGION_WHITELIST
    )


def can_view_stats_ddets_log(request):
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DDETS_LOG
    )


def can_view_stats_dreets_iae(request):
    """
    Users of a DREETS IAE can view the confidential DREETS IAE stats of their region only.
    """
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DREETS_IAE
    )


def can_view_stats_dreets_iae_ph_prescription(request):
    return (
        can_view_stats_dreets_iae(request)
        and request.current_organization.region in settings.STATS_PH_PRESCRIPTION_REGION_WHITELIST
    )


def can_view_stats_dgefp(request):
    """
    Users of the DGEFP institution can view the confidential DGEFP stats for all regions and departments.
    """
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DGEFP_IAE
    )


def can_view_stats_dihal(request):
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DIHAL
    )


def can_view_stats_drihl(request):
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DRIHL
    )


def can_view_stats_iae_network(request):
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.IAE_NETWORK
    )


def get_stats_pe_departments(request):
    if not can_view_stats_pe(request):
        raise PermissionDenied
    if request.current_organization.is_dgpe:
        return DEPARTMENTS.keys()
    if request.current_organization.is_drpe:
        return REGIONS[request.current_organization.region]
    if request.current_organization.is_dtpe:
        departments = DTPE_SAFIR_CODE_TO_DEPARTMENTS[request.current_organization.code_safir_pole_emploi]
        return [request.current_organization.department] if departments is None else departments
    return [request.current_organization.department]
