#################################################
###################### RSA ######################
#################################################
def rsa_certified_mocker():
    # https://github.com/etalab/siade_staging_data/blob/develop/payloads/api_particulier_v2_cnav_revenu_solidarite_active/200_beneficiaire_majoration.yaml
    return {"status": "beneficiaire", "majoration": True, "dateDebut": "2024-08-01", "dateFin": None}


def rsa_not_certified_mocker():
    return {"status": "non_beneficiaire", "majoration": None, "dateDebut": None, "dateFin": None}


def rsa_not_found_mocker():
    # https://github.com/etalab/siade_staging_data/blob/develop/payloads/api_particulier_v2_cnav_revenu_solidarite_active/404.yaml
    return {
        "error": "not_found",
        "reason": "Dossier allocataire inexistant. Le document ne peut être édité.",
        "message": "Dossier allocataire inexistant. Le document ne peut être édité.",
    }


def rsa_data_provider_error():
    reason = (
        "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service. L'équipe "
        "technique a été notifiée de cette erreur pour investigation."
    )
    return {
        "error": "provider_unknown_error",
        "reason": reason,
        "message": reason,
    }


#################################################
###################### AAH ######################
#################################################
def aah_certified_mocker():
    # https://particulier.api.gouv.fr/developpeurs/openapi#tag/Prestations-sociales/paths/~1api~1v2~1allocation-adulte-handicape/get
    return {"status": "beneficiaire", "dateDebut": "2024-08-01"}
