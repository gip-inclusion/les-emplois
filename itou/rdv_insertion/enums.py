from django.db import models


class InvitationType(models.TextChoices):
    SMS = "sms", "SMS"
    EMAIL = "email", "E-mail"
    POSTAL = "postal", "Courrier"


class InvitationStatus(models.TextChoices):
    SENT = "sent", "Envoyée"
    DELIVERED = "delivered", "Délivrée"
    NOT_DELIVERED = "not_delivered", "Non délivrée"
    OPENED = "opened", "Ouverte"


class ParticipationStatus(models.TextChoices):
    UNKNOWN = "unknown", "Non déterminé"
    SEEN = "seen", "RDV honoré"
    EXCUSED = "excused", "RDV annulé à l’initiative de l’usager"
    REVOKED = "revoked", "RDV annulé à l’initiative du service"
    NOSHOW = "noshow", "Absence non excusée au RDV"


class InvitationRequestReasonCategory(models.TextChoices):
    RSA_DROITS_DEVOIRS = "rsa_droits_devoirs", "RSA - droits et devoirs"
    RSA_ORIENTATION = "rsa_orientation", "RSA orientation"
    RSA_ORIENTATION_FRANCE_TRAVAIL = "rsa_orientation_france_travail", "RSA orientation France Travail"
    RSA_ACCOMPAGNEMENT = "rsa_accompagnement", "RSA accompagnement"
    RSA_ACCOMPAGNEMENT_SOCIAL = "rsa_accompagnement_social", "RSA accompagnement social"
    RSA_ACCOMPAGNEMENT_SOCIOPRO = "rsa_accompagnement_sociopro", "RSA accompagnement socio-pro"
    RSA_ORIENTATION_ON_PHONE_PLATFORM = (
        "rsa_orientation_on_phone_platform",
        "RSA orientation sur plateforme téléphonique",
    )
    RSA_CER_SIGNATURE = "rsa_cer_signature", "RSA signature CER"
    RSA_INSERTION_OFFER = "rsa_insertion_offer", "RSA offre insertion pro"
    RSA_FOLLOW_UP = "rsa_follow_up", "RSA suivi"
    RSA_MAIN_TENDUE = "rsa_main_tendue", "RSA Main Tendue"
    RSA_ATELIER_COLLECTIF_MANDATORY = "rsa_atelier_collectif_mandatory", "RSA Atelier collectif"
    RSA_SPIE = "rsa_spie", "RSA SPIE"
    RSA_INTEGRATION_INFORMATION = "rsa_integration_information", "RSA Information d'intégration"
    RSA_ATELIER_COMPETENCES = "rsa_atelier_competences", "RSA Atelier compétences"
    RSA_ATELIER_RENCONTRES_PRO = "rsa_atelier_rencontres_pro", "RSA Atelier rencontres professionnelles"
    PSYCHOLOGUE = "psychologue", "Psychologue"
    RSA_ORIENTATION_FREELANCE = "rsa_orientation_freelance", "RSA orientation - travailleurs indépendants"
    RSA_ORIENTATION_COACHING = "rsa_orientation_coaching", "RSA orientation - coaching emploi"
    ATELIER_ENFANTS_ADOS = "atelier_enfants_ados", "Atelier Enfants / Ados"
    RSA_ORIENTATION_FILE_ACTIVE = "rsa_orientation_file_active", "RSA orientation file active"
    SIAE_INTERVIEW = "siae_interview", "Entretien SIAE"
    SIAE_COLLECTIVE_INFORMATION = "siae_collective_information", "Info coll. SIAE"
    SIAE_FOLLOW_UP = "siae_follow_up", "Suivi SIAE"
