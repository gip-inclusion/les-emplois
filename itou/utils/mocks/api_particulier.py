def rsa_certified_mocker():
    # https://github.com/etalab/siade_staging_data/blob/develop/payloads/api_particulier_v2_cnav_revenu_solidarite_active/200_beneficiaire_majoration.yaml
    return {"status": "beneficiaire", "majoration": True, "dateDebut": "2024-08-01", "dateFin": "2024-10-31"}


def rsa_not_certified_mocker():
    return {"status": "non_beneficiaire", "majoration": None, "dateDebut": None, "dateFin": None}


def rsa_not_found_mocker():
    # https://github.com/etalab/siade_staging_data/blob/develop/payloads/api_particulier_v2_cnav_revenu_solidarite_active/404.yaml
    return {
        "error": "not_found",
        "reason": "Dossier allocataire inexistant. Le document ne peut être édité.",
        "message": "Dossier allocataire inexistant. Le document ne peut être édité.",
    }
