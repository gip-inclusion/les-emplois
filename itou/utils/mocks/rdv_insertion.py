RDV_INSERTION_AUTH_SUCCESS_BODY = {
    "data": {
        "email": "tech@inclusion.beta.gouv.fr",
        "first_name": "Jean",
        "last_name": "Teste",
        "provider": "email",
        "uid": "tech@inclusion.beta.gouv.fr",
        "id": 1,
        "deleted_at": None,
        "email_original": None,
        "allow_password_change": False,
        "rdv_notifications_level": "others",
        "unknown_past_rdv_count": 0,
        "display_saturdays": False,
        "display_cancelled_rdv": True,
        "plage_ouverture_notification_level": "all",
        "absence_notification_level": "all",
        "external_id": None,
        "calendar_uid": None,
        "microsoft_graph_token": None,
        "refresh_microsoft_graph_token": None,
        "cnfs_secondary_email": None,
        "outlook_disconnect_in_progress": False,
        "account_deletion_warning_sent_at": None,
        "inclusion_connect_open_id_sub": None,
    }
}

RDV_INSERTION_AUTH_SUCCESS_HEADERS = {
    "access-token": "V60eQsbHA6m2hTIsHzD-Jw",
    "client": "KhtrOXm0US_kCq79JhJAyA",
    "uid": "tech@inclusion.beta.gouv.fr",
}

RDV_INSERTION_AUTH_FAILURE_BODY = {
    "success": False,
    "errors": [
        "Mot de passe ou identifiant invalide.",
    ],
}

RDV_INSERTION_CREATE_AND_INVITE_SUCCESS_BODY = {
    "success": True,
    "user": {
        "id": 1,
        "uid": None,
        "affiliation_number": None,
        "role": "demandeur",
        "created_at": "1970-01-01T00:00:00",
        "department_internal_id": None,
        "first_name": "Jean",
        "last_name": "Teste",
        "title": "monsieur",
        "address": "112 Quai de Jemmapes, 75010 Paris",
        "phone_number": None,
        "email": "tech@inclusion.beta.gouv.fr",
        "birth_date": "1970-01-01",
        "rights_opening_date": "2024-06-22",
        "birth_name": None,
        "rdv_solidarites_user_id": 1234,
        "nir": None,
        "carnet_de_bord_carnet_id": None,
        "france_travail_id": "FT ID",
        "referents": [],
    },
    "invitations": [
        {
            "id": 4321,
            "format": "email",
            "clicked": False,
            "rdv_with_referents": False,
            "created_at": "1970-01-01T00:00:00",
            "motif_category": {"id": 1, "short_name": "siae_interview", "name": "Entretien SIAE"},
            "delivery_status": "delivered",
        }
    ],
}

RDV_INSERTION_CREATE_AND_INVITE_FAILURE_BODY = {
    "success": False,
    "errors": [
        "Erreur inconnue",
    ],
}
