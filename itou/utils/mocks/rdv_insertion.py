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
