from django.conf import settings
from django.core.cache import caches

from itou.common_apps.address.departments import DEPARTMENTS, REGIONS
from itou.companies.models import Company
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.metabase.models import DatumKey
from itou.prescribers.enums import (
    DTFT_SAFIR_CODE_TO_DEPARTMENTS,
    PrescriberOrganizationKind,
)
from itou.users.enums import UserKind


STATS_PH_ORGANISATION_KIND_WHITELIST = [
    PrescriberOrganizationKind.CAP_EMPLOI,
    PrescriberOrganizationKind.CHRS,
    PrescriberOrganizationKind.CHU,
    PrescriberOrganizationKind.ML,
    PrescriberOrganizationKind.OIL,
    PrescriberOrganizationKind.PLIE,
    PrescriberOrganizationKind.RS_FJT,
]


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


def can_view_stats_siae_etp(request):
    """
    Non official stats with very specific access rights.
    """
    return (
        can_view_stats_siae(request)
        and request.is_current_organization_admin
        and request.user.pk in settings.STATS_SIAE_USER_PK_WHITELIST
    )


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
        request.from_authorized_prescriber
        and request.current_organization.kind == PrescriberOrganizationKind.DEPT
        and not request.current_organization.is_brsa
    )


def can_view_stats_ft(request):
    return request.from_authorized_prescriber and request.current_organization.kind == PrescriberOrganizationKind.FT


def can_view_stats_ph(request):
    return request.from_authorized_prescriber


def can_view_stats_ph_whitelisted(request):
    return can_view_stats_ph(request) and request.current_organization.kind in STATS_PH_ORGANISATION_KIND_WHITELIST


def can_view_stats_ddets_iae(request):
    """
    Users of a DDETS IAE can view the confidential DDETS IAE stats of their department only.
    """
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.DDETS_IAE
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


def can_view_stats_dgefp_iae(request):
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


def can_view_stats_convergence(request):
    return (
        request.user.is_labor_inspector
        and isinstance(request.current_organization, Institution)
        and request.current_organization.kind == InstitutionKind.CONVERGENCE
    )


def can_view_stats_staff(request):
    return request.user.is_authenticated and (request.user.kind == UserKind.ITOU_STAFF or request.user.is_staff)


def get_stats_ft_departments(current_organization):
    if current_organization.is_dgft:
        return DEPARTMENTS.keys()
    if current_organization.is_drft:
        return REGIONS[current_organization.region]
    if current_organization.is_dtft:
        departments = DTFT_SAFIR_CODE_TO_DEPARTMENTS[current_organization.code_safir_pole_emploi]
        return [current_organization.department] if departments is None else departments
    return [current_organization.department]


def get_stats_for_institution(institution: Institution, datum_key: DatumKey, *, is_percentage=False):
    match institution.kind:
        case (
            InstitutionKind.DGEFP_GEIQ
            | InstitutionKind.DGEFP_IAE
            | InstitutionKind.DIHAL
            | InstitutionKind.IAE_NETWORK
        ):
            grouped_by = None
        case InstitutionKind.DREETS_GEIQ | InstitutionKind.DREETS_IAE | InstitutionKind.DRIHL:
            grouped_by = "region"
        case InstitutionKind.DDETS_GEIQ | InstitutionKind.DDETS_IAE | InstitutionKind.DDETS_LOG:
            grouped_by = "department"
        case _:
            raise ValueError

    datum_key_to_fetch = datum_key.grouped_by(grouped_by) if grouped_by else datum_key
    data = caches["stats"].get(datum_key_to_fetch)
    value = data.get(getattr(institution, grouped_by)) if grouped_by and data else data
    return value * 100 if is_percentage and value else value
