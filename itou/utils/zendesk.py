import logging

from itou.companies.enums import CompanyKind
from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind


logger = logging.getLogger(__name__)


def serialize_zendesk_params(request):
    """
    Use the request to pre-fill the form on zendesk.

    Warning : There's no clean API : it's only values set in Zendesk admin,
    therefore any change on zendesk can render part of this function obsolete.
    Since any invalid value will be discarded by zendesk, it won't break
    the form page on zendesk, the user will just have to fill it manually instead.
    """
    zendesk_user_kind = None
    zendesk_company_kind = None
    zendesk_institution_kind = None
    zendesk_prescriber_kind = None
    if request.user.is_job_seeker:
        zendesk_user_kind = "candidat"

    elif request.user.is_prescriber:
        if request.from_authorized_prescriber:
            zendesk_user_kind = "prescripteur_prescripteur-habilité"
        else:
            zendesk_user_kind = "prescripteur_orienteur"
        if request.current_organization:
            if request.current_organization.kind == PrescriberOrganizationKind.ASE:
                zendesk_prescriber_kind = "ase-orga-cd"
            elif request.current_organization.kind == PrescriberOrganizationKind.CAP_EMPLOI:
                zendesk_prescriber_kind = "cap-emploi"
            elif request.current_organization.kind == PrescriberOrganizationKind.FT:
                zendesk_prescriber_kind = "pole-emploi"
            elif request.current_organization.kind == PrescriberOrganizationKind.ML:
                zendesk_prescriber_kind = "mission-locale"
            elif request.current_organization.kind == PrescriberOrganizationKind.ODC:
                zendesk_prescriber_kind = "orga-deleguee-cd"
            elif request.current_organization.kind == PrescriberOrganizationKind.OHPD:
                zendesk_prescriber_kind = "orga-habilite-prefet"
            elif request.current_organization.kind == PrescriberOrganizationKind.PENSION:
                zendesk_prescriber_kind = "pensions-familles-residence-accueil"
            elif request.current_organization.kind == PrescriberOrganizationKind.PIJ_BIJ:
                zendesk_prescriber_kind = "pij-bij"
            elif request.current_organization.kind == PrescriberOrganizationKind.RS_FJT:
                zendesk_prescriber_kind = "residence-fjt"
            elif request.current_organization.kind == PrescriberOrganizationKind.DEPT:
                zendesk_prescriber_kind = "services-sociaux-cd"
            elif request.current_organization.kind in [
                PrescriberOrganizationKind.ORIENTEUR,
                PrescriberOrganizationKind.OCASF,
                PrescriberOrganizationKind.PREVENTION,
            ]:
                zendesk_prescriber_kind = "autre"
            else:
                zendesk_prescriber_kind = request.current_organization.kind.lower()

    elif request.user.is_employer:
        if request.current_organization:  # We might not have one in the invitation flow
            zendesk_company_kind = request.current_organization.kind.lower()
            if request.current_organization.is_subject_to_eligibility_rules:
                zendesk_user_kind = "employeur_siae"
            elif request.current_organization.kind == CompanyKind.GEIQ:
                zendesk_user_kind = "employeur_geiq"
            elif request.current_organization.kind == CompanyKind.OPCS:
                zendesk_user_kind = "employeur_facilitateur"
            elif request.current_organization.kind in [CompanyKind.EA, CompanyKind.EATT]:
                zendesk_user_kind = "employeur_ea-eatt"
            else:
                logger.error("Invalid employer kind : this should not happen")

    elif request.user.is_labor_inspector:
        zendesk_user_kind = "ddets-dreets"
        if request.current_organization:  # We might not have one in the invitation flow
            if request.current_organization.kind in [
                InstitutionKind.DDETS_GEIQ,
                InstitutionKind.DDETS_IAE,
                InstitutionKind.DDETS_LOG,
            ]:
                zendesk_institution_kind = "ddets"
            elif request.current_organization.kind in [
                InstitutionKind.DREETS_GEIQ,
                InstitutionKind.DREETS_IAE,
                InstitutionKind.DRIHL,
            ]:
                zendesk_institution_kind = "dreets"
            elif request.current_organization.kind in [
                InstitutionKind.DGEFP_GEIQ,
                InstitutionKind.DGEFP_IAE,
            ]:
                zendesk_institution_kind = "dgefp"
            else:
                zendesk_institution_kind = "autre-admin-centarle"

    params = {
        "tf_anonymous_requester_email": request.user.email,
        "tf_30473760509585": request.user.phone,
        "tf_15923279049745": zendesk_user_kind,
        "tf_16096444701329": zendesk_company_kind,
        "tf_16096355658513": zendesk_institution_kind,
        "tf_16096272057233": zendesk_prescriber_kind,
    }

    if current_organization := getattr(request, "current_organization", None):
        params["tf_16096639918353"] = getattr(request.current_organization, "siret", None)
        params["tf_16096931518225"] = current_organization.name

    return params
