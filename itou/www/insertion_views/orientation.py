def build_dora_orientation_payload(
    *,
    service,
    job_seeker,
    referent_data,
    documents_data,
    prescriber,
    organization,
):
    payload = {
        "di_service_id": service.uid,
        "beneficiary_first_name": job_seeker.first_name,
        "beneficiary_last_name": job_seeker.last_name,
        "beneficiary_email": job_seeker.email,
        "referent_first_name": referent_data["referent_first_name"],
        "referent_last_name": referent_data["referent_last_name"],
        "referent_email": referent_data["referent_email"],
        "referent_phone": referent_data["referent_phone"],
        "data_protection_commitment": documents_data["gdpr_consent"],
    }

    if job_seeker.phone:
        payload["beneficiary_phone"] = job_seeker.phone

    if orientation_reason := referent_data.get("orientation_reason"):
        payload["orientation_reasons"] = orientation_reason

    if pole_emploi_id := job_seeker.jobseeker_profile.pole_emploi_id:
        payload["beneficiary_france_travail_number"] = pole_emploi_id

    if organization and prescriber:
        emplois_data = {
            "beneficiary_id": str(job_seeker.public_id),
            "structure_id": str(organization.uid),
            "structure_name": organization.name,
            "prescriber_id": str(prescriber.public_id),
            "prescriber_email": prescriber.email,
            "prescriber_first_name": prescriber.first_name,
            "prescriber_last_name": prescriber.last_name,
        }
        if prescriber_phone := prescriber.phone or referent_data["referent_phone"]:
            emplois_data["prescriber_phone"] = prescriber_phone
        if organization.siret:
            emplois_data["structure_siret"] = organization.siret
        payload["emplois_data"] = emplois_data

    return payload
