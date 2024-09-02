from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from itou.companies.enums import ContractType


def get_export_ts():
    return f"{timezone.localdate().strftime('%Y-%m-%d')}_{timezone.localtime().strftime('%H-%M-%S')}"


def _getattrs(obj, *attrs):
    result = obj
    for attr in attrs:
        try:
            result = getattr(result, attr)
        except ObjectDoesNotExist:
            return ""
        else:
            if result is None:
                return ""
    return result


def all_or_empty_list(obj, *attrs):
    manager = _getattrs(obj, *attrs)
    if manager:
        return manager.all()
    return []


def export_row(spec, obj):
    return [f(obj) for f in spec.values()]


job_app_export_spec = {
    "job_seeker_title": lambda job_app: job_app.job_seeker.title,
    "job_seeker_first_name": lambda job_app: job_app.job_seeker.first_name,
    "job_seeker_last_name": lambda job_app: job_app.job_seeker.last_name,
    "job_seeker_nir": lambda job_app: job_app.job_seeker.jobseeker_profile.nir,
    "job_seeker_france_travail_id": lambda job_app: job_app.job_seeker.jobseeker_profile.pole_emploi_id,
    "job_seeker_ft_obfuscated_nir": lambda job_app: job_app.job_seeker.jobseeker_profile.pe_obfuscated_nir,
    "job_seeker_date_joined": lambda job_app: job_app.job_seeker.date_joined.isoformat(),
    "job_seeker_birth_date": lambda job_app: job_app.job_seeker.jobseeker_profile.birthdate,
    "job_seeker_birth_municipality": lambda job_app: _getattrs(job_app.job_seeker.jobseeker_profile, "birth_place"),
    "job_seeker_birth_country": lambda job_app: _getattrs(job_app.job_seeker.jobseeker_profile, "birth_country"),
    "job_seeker_email": lambda job_app: job_app.job_seeker.email,
    "job_seeker_phone": lambda job_app: job_app.job_seeker.phone,
    "job_seeker_identity_provider": lambda job_app: job_app.job_seeker.identity_provider,
    "job_seeker_created_by": lambda job_app: _getattrs(job_app.job_seeker, "created_by"),
    "job_seeker_address1_line_1": lambda job_app: job_app.job_seeker.address_line_1,
    "job_seeker_address1_line_2": lambda job_app: job_app.job_seeker.address_line_2,
    "job_seeker_address1_post_code": lambda job_app: job_app.job_seeker.post_code,
    "job_seeker_address1_city": lambda job_app: job_app.job_seeker.city,
    "job_seeker_address1_city_code_insee": lambda job_app: _getattrs(job_app.job_seeker, "insee_city", "code_insee"),
    "job_seeker_address1_coords": lambda job_app: f"{job_app.job_seeker.coords.x}; {job_app.job_seeker.coords.y}"
    if job_app.job_seeker.coords
    else "",
    "job_seeker_address1_geocoding_score": lambda job_app: job_app.job_seeker.geocoding_score,
    "job_seeker_address1_BAN_API_address": lambda job_app: job_app.job_seeker.ban_api_resolved_address,
    "job_seeker_address2_lane_number": lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_lane_number,
    "job_seeker_address2_non_std_extension": (
        lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_non_std_extension
    ),
    "job_seeker_address2_lane_type": lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_lane_type,
    "job_seeker_address2_lane_name": lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_lane_name,
    "job_seeker_address2_additional_address": (
        lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_additional_address
    ),
    "job_seeker_address2_post_code": lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_post_code,
    "job_seeker_address2_municipality": lambda job_app: job_app.job_seeker.jobseeker_profile.hexa_commune,
    "job_seeker_education_level": lambda job_app: job_app.job_seeker.jobseeker_profile.education_level,
    "job_seeker_resourceless": lambda job_app: job_app.job_seeker.jobseeker_profile.resourceless,
    "job_seeker_rqth": lambda job_app: job_app.job_seeker.jobseeker_profile.rqth_employee,
    "job_seeker_oeth": lambda job_app: job_app.job_seeker.jobseeker_profile.oeth_employee,
    "job_seeker_france_travail_since": (
        lambda job_app: job_app.job_seeker.jobseeker_profile.get_pole_emploi_since_display()
    ),
    "job_seeker_unemployed_since": lambda job_app: job_app.job_seeker.jobseeker_profile.get_unemployed_since_display(),
    "job_seeker_has_rsa_allocation": lambda job_app: job_app.job_seeker.jobseeker_profile.has_rsa_allocation,
    "job_seeker_rsa_allocation_since": (
        lambda job_app: job_app.job_seeker.jobseeker_profile.get_rsa_allocation_since_display()
    ),
    "job_seeker_has_ass_allocation": lambda job_app: job_app.job_seeker.jobseeker_profile.has_ass_allocation,
    "job_seeker_ass_allocation_since": lambda job_app: (
        job_app.job_seeker.jobseeker_profile.get_ass_allocation_since_display()
    ),
    "job_seeker_has_aah_allocation": lambda job_app: job_app.job_seeker.jobseeker_profile.has_aah_allocation,
    "job_seeker_aah_allocation_since": (
        lambda job_app: job_app.job_seeker.jobseeker_profile.get_aah_allocation_since_display()
    ),
    "job_seeker_ata_allocation_since": (
        lambda job_app: job_app.job_seeker.jobseeker_profile.get_ata_allocation_since_display()
    ),
    "application_eligibility_diagnosis_author_kind": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_kind"
    ),
    "application_eligibility_diagnosis_author_siae_kind": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_siae", "kind"
    ),
    "application_eligibility_diagnosis_author_siae_siret": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_siae", "siret"
    ),
    "application_eligibility_diagnosis_author_siae_naf": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_siae", "naf"
    ),
    "application_eligibility_diagnosis_author_siae_name": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_siae", "display_name"
    ),
    "application_eligibility_diagnosis_author_prescriber_organization_siret": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_prescriber_organization", "siret"
    ),
    "application_eligibility_diagnosis_author_prescriber_organization_kind": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_prescriber_organization", "kind"
    ),
    "application_eligibility_diagnosis_author_prescriber_organization_is_habilitated": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_prescriber_organization", "is_authorized"
    ),
    "application_eligibility_diagnosis_author_prescriber_organization_code_safir": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "author_prescriber_organization", "code_safir_pole_emploi"
    ),
    "application_eligibility_diagnosis_expires_at": lambda job_app: _getattrs(
        job_app, "eligibility_diagnosis", "expires_at"
    ),
    "application_eligibility_diagnosis_administrative_criteria": lambda job_app: " | ".join(
        crit.name for crit in all_or_empty_list(job_app, "eligibility_diagnosis", "administrative_criteria")
    ),
    "application_to_company_kind": lambda job_app: job_app.to_company.kind,
    "application_to_company_siret": lambda job_app: job_app.to_company.siret,
    "application_to_company_naf": lambda job_app: job_app.to_company.naf,
    "application_to_company_name": lambda job_app: job_app.to_company.display_name,
    "sender": lambda job_app: job_app.sender,
    "sender_company_kind": lambda job_app: _getattrs(job_app, "sender_company", "kind"),
    "sender_company_siret": lambda job_app: _getattrs(job_app, "sender_company", "siret"),
    "sender_company_naf": lambda job_app: _getattrs(job_app, "sender_company", "naf"),
    "sender_company_name": lambda job_app: _getattrs(job_app, "sender_company", "display_name"),
    "sender_prescriber_organization_siret": lambda job_app: _getattrs(
        job_app, "sender_prescriber_organization", "siret"
    ),
    "sender_prescriber_organization_kind": lambda job_app: _getattrs(
        job_app, "sender_prescriber_organization", "kind"
    ),
    "sender_prescriber_organization_is_habilitated": lambda job_app: _getattrs(
        job_app, "sender_prescriber_organization", "is_authorized"
    ),
    "sender_prescriber_organization_code_safir": lambda job_app: _getattrs(
        job_app, "sender_prescriber_organization", "code_safir_pole_emploi"
    ),
    "selected_jobs": lambda job_app: " | ".join(job.display_name for job in job_app.selected_jobs.all())
    or "Candidature spontanée",
    "hired_for_job_name": lambda job_app: _getattrs(job_app, "hired_job", "display_name"),
    "hired_for_job_appellation_code": lambda job_app: _getattrs(job_app, "hired_job", "appellation", "code"),
    "hired_for_job_appellation_name": lambda job_app: _getattrs(job_app, "hired_job", "appellation", "name"),
    "hired_for_job_ROME_code": lambda job_app: _getattrs(job_app, "hired_job", "appellation", "rome", "code"),
    "hired_for_job_ROME_name": lambda job_app: _getattrs(job_app, "hired_job", "appellation", "rome", "name"),
    "hired_for_job_contract_type":  # Handle OTHER
    lambda job_app: (
        _getattrs(job_app, "hired_job", "contract_type")
        if _getattrs(job_app, "hired_job", "contract_type") != ContractType.OTHER
        else _getattrs(job_app, "hired_job", "other_contract_type")
    ),
    "hired_for_job_contract_nature": lambda job_app: _getattrs(job_app, "hired_job", "contract_nature"),
    "hired_for_job_location": lambda job_app: _getattrs(job_app, "hired_job", "location"),
    "hired_for_job_location_hours_per_week": lambda job_app: _getattrs(job_app, "hired_job", "hours_per_week"),
    "hiring_start_at": lambda job_app: job_app.hiring_start_at,
    "hiring_end_at": lambda job_app: job_app.hiring_end_at,
    "contract_type": lambda job_app: job_app.contract_type,
    "contract_type_details": lambda job_app: job_app.contract_type_details,
    "nb_hours_per_week": lambda job_app: job_app.nb_hours_per_week,
    "qualification_type": lambda job_app: job_app.qualification_type,
    "qualification_level": lambda job_app: job_app.qualification_level,
    "planned_training_hours": lambda job_app: job_app.planned_training_hours,
    "inverted_vae_contract": lambda job_app: job_app.inverted_vae_contract,
    "PASS_IAE_number": lambda job_app: _getattrs(job_app, "approval", "number"),
    "PASS_IAE_start_at": lambda job_app: _getattrs(job_app, "approval", "start_at"),
    "PASS_IAE_end_at": lambda job_app: _getattrs(job_app, "approval", "end_at"),
    "PASS_IAE_prolongations": lambda job_app: " | ".join(
        f"[{p.start_at};{p.end_at}] ({p.reason})" for p in all_or_empty_list(job_app, "approval", "prolongation_set")
    ),
    "PASS_IAE_suspensions": lambda job_app: " | ".join(
        f"[{s.start_at};{s.end_at}] ({s.reason})" for s in all_or_empty_list(job_app, "approval", "suspension_set")
    ),
}


def get_org(membership):
    if company := getattr(membership, "company", None):
        return company
    if prescriber_organization := getattr(membership, "organization", None):
        return prescriber_organization
    raise ValueError


cta_export_spec = {
    "Utilisateur - type": (
        lambda membership: "Employeur"
        if hasattr(membership, "company")
        else ("Prescripteur habitité" if membership.organization.is_authorized else "Orienteur")
    ),
    "Structure - type": lambda membership: get_org(membership).kind,
    "Structure - nom": lambda membership: get_org(membership).name,
    "Structure - SIRET": lambda membership: get_org(membership).siret,
    "Structure - adresse ligne 1": lambda membership: get_org(membership).address_line_1,
    "Structure - adresse ligne 2": lambda membership: get_org(membership).address_line_2,
    "Structure - code postal": lambda membership: get_org(membership).post_code,
    "Structure - ville": lambda membership: get_org(membership).city,
    "Structure - département": lambda membership: get_org(membership).department,
    "Structure - région": lambda membership: get_org(membership).region,
    "Utilisateur - prénom": lambda membership: membership.user.first_name,
    "Utilisateur - nom": lambda membership: membership.user.last_name,
    "Utilisateur - e-mail": lambda membership: membership.user.email,
    "Administrateur ?": lambda membership: "Oui" if membership.is_admin else "Non",
    "Utilisateur - date d'inscription": lambda membership: membership.user.date_joined.strftime("%d-%m-%Y"),
}
