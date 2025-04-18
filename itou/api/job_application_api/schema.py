from drf_spectacular.utils import OpenApiExample


job_application_search_request_example = OpenApiExample(
    "Exemple de recherche de candidatures (requête)",
    request_only=True,
    value={
        "nir": "269054958815780",
        "nom": "DURAND",
        "prenom": "NATHALIE",
        "date_naissance": "1969-05-12",
    },
)

job_application_search_response_valid_example = OpenApiExample(
    "Exemple de recherche de candidatures (réponse)",
    response_only=True,
    status_codes=[200],
    value={
        "count": 2,
        "next": None,
        "previous": None,
        "results": [
            {
                "identifiant_unique": "e1b89c73-b064-4351-8e2d-b6e1a1359c27",
                "cree_le": "2025-02-06T14:48:06.595973+01:00",
                "mis_a_jour_le": "2025-02-06T17:15:22.654892+01:00",
                "dernier_changement_le": "2025-02-06T17:15:22.654892+01:00",
                "statut": "obsolete",
                "candidat_nir": "269054958815780",
                "candidat_nom": "Durand",
                "candidat_prenom": "Nathalie",
                "candidat_date_naissance": "1969-05-12",
                "candidat_email": "nathalie.durand@inclusion.gouv.fr",
                "candidat_telephone": "0123456789",
                "candidat_pass_iae_statut": None,
                "candidat_pass_iae_numero": None,
                "candidat_pass_iae_date_debut": None,
                "candidat_pass_iae_date_fin": None,
                "entreprise_type": "EI",
                "entreprise_nom": "Plateforme de l'Inclusion",
                "entreprise_siret": "13003013300016",
                "entreprise_adresse": "127 rue de Grenelle, 75007 Paris",
                "entreprise_employeur_email": "",
                "orientation_emetteur_type": "job_seeker",
                "orientation_emetteur_sous_type": None,
                "orientation_emetteur_nom": "Durand",
                "orientation_emetteur_prenom": "Nathalie",
                "orientation_emetteur_email": None,
                "orientation_emetteur_organisme": None,
                "orientation_emetteur_organisme_telephone": None,
                "orientation_postes_recherches": [],
                "orientation_candidat_message": "Message à l’employeur",
                "orientation_candidat_cv": "",
                "contrat_date_debut": None,
                "contrat_date_fin": None,
                "contrat_poste_retenu": None,
            },
            {
                "identifiant_unique": "2a30f968-02c9-48c6-ac3f-d8611fdcc46b",
                "cree_le": "2025-02-06T10:52:25.678156+01:00",
                "mis_a_jour_le": "2025-02-06T17:25:33.458745+01:00",
                "dernier_changement_le": "2025-02-06T10:52:25.678156+01:00",
                "statut": "accepted",
                "candidat_nir": "269054958815780",
                "candidat_nom": "Durand",
                "candidat_prenom": "Nathalie",
                "candidat_date_naissance": "1969-05-12",
                "candidat_email": "nathalie.durand@inclusion.gouv.fr",
                "candidat_telephone": "0123456789",
                "candidat_pass_iae_statut": "VALID",
                "candidat_pass_iae_numero": "012345678901",
                "candidat_pass_iae_date_debut": "2022-02-02",
                "candidat_pass_iae_date_fin": "2027-08-09",
                "entreprise_type": "EI",
                "entreprise_nom": "Plateforme de l'Inclusion",
                "entreprise_siret": "13003013300016",
                "entreprise_adresse": "127 rue de Grenelle, 75007 Paris",
                "entreprise_employeur_email": "john.doe@inclusion.gouv.fr",
                "orientation_emetteur_type": "prescriber",
                "orientation_emetteur_sous_type": None,
                "orientation_emetteur_nom": "Dufour",
                "orientation_emetteur_prenom": "André",
                "orientation_emetteur_email": "",
                "orientation_emetteur_organisme": "POLE EMPLOI - PARIS",
                "orientation_emetteur_organisme_telephone": "+33 1 23 45 67 89",
                "orientation_postes_recherches": [
                    {
                        "rome": "I1103",
                        "titre": "Supervision d'entretien et gestion de véhicules",
                        "ville": "Paris",
                    },
                    {
                        "rome": "I1604",
                        "titre": "Mécanique automobile et entretien de véhicules",
                        "ville": "Paris",
                    },
                ],
                "orientation_candidat_message": "Bonjour je souhaite candidater à ce poste\nMerci.",
                "orientation_candidat_cv": "",
                "contrat_date_debut": "2025-02-06",
                "contrat_date_fin": "2027-02-05",
                "contrat_poste_retenu": {
                    "rome": "I1604",
                    "titre": "Mécanique automobile et entretien de véhicules",
                    "ville": "Paris",
                },
            },
        ],
    },
)

job_application_search_response_valid_no_results_example = OpenApiExample(
    "Exemple de recherche de candidatures sans résultats (réponse)",
    response_only=True,
    status_codes=[200],
    value={
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    },
)

job_application_search_response_invalid_example = OpenApiExample(
    "Exemple de recherche de candidatures invalide (réponse)",
    response_only=True,
    status_codes=[400],
    value={
        "nom": ["Ce champ est obligatoire."],
        "prenom": ["Ce champ est obligatoire."],
        "date_naissance": ["Ce champ est obligatoire."],
    },
)
