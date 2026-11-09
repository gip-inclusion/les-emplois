RDV_INSERTION_AUTH_SUCCESS_BODY = {
    "data": {
        "email": "tech.emplois@inclusion.gouv.fr",
        "first_name": "Jean",
        "last_name": "Teste",
        "provider": "email",
        "uid": "tech.emplois@inclusion.gouv.fr",
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
    "uid": "tech.emplois@inclusion.gouv.fr",
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
        "email": "tech.emplois@inclusion.gouv.fr",
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


RDV_INSERTION_WEBHOOK_INVITATION_HEADERS = {
    "Host": "localhost",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Rdvi-Signature": "9ccf14d92f839a383ad27177e9ff4fd346b4d2295a36e842378fca3486cd5152",
}


RDV_INSERTION_WEBHOOK_INVITATION_BODY = {
    "data": {
        "id": 4806,
        "user": {
            "id": 3432,
            "uid": None,
            "role": "demandeur",
            "email": "tech.emplois@inclusion.gouv.fr",
            "title": "madame",
            "address": "102 Quai de Jemmapes, 75010 Paris 10ème",
            "last_name": "Test",
            "birth_date": "1969-05-01",
            "birth_name": None,
            "created_at": "2024-08-07T17:01:30.719+02:00",
            "first_name": "Jeanne",
            "phone_number": None,
            "france_travail_id": None,
            "affiliation_number": None,
            "rights_opening_date": None,
            "rdv_solidarites_user_id": 5527,
            "carnet_de_bord_carnet_id": None,
        },
        "format": "email",
        "clicked": True,
        "created_at": "2024-08-15T19:23:08.107+02:00",
        "delivered_at": "2024-08-16T08:17:08+02:00",
        "motif_category": {"id": 16, "name": "Entretien SIAE", "short_name": "siae_interview"},
        "delivery_status": None,
        "rdv_with_referents": False,
    },
    "meta": {"event": "updated", "model": "Invitation", "timestamp": "2024-08-15 19:23:12 +0200"},
}


RDV_INSERTION_WEBHOOK_APPOINTMENT_HEADERS = {
    "Host": "localhost",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Rdvi-Signature": "1504bcba3bd89bd6ff409b9b80463c5ebf120665e3978be7d11a39cb18a4d189",
}


RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY = {
    "data": {
        "id": 1261,
        "lieu": {
            "name": "PDI",
            "address": "6 Boulevard Saint-Denis, Paris, 75010",
            "phone_number": "",
            "rdv_solidarites_lieu_id": 1026,
        },
        "uuid": "37141381-ac77-41a6-8a7e-748d1c9439d5",
        "motif": {
            "name": "Entretien d'embauche",
            "collectif": False,
            "follow_up": False,
            "location_type": "public_office",
            "motif_category": {"id": 16, "name": "Entretien SIAE", "short_name": "siae_interview"},
            "rdv_solidarites_motif_id": 1443,
        },
        "users": [
            {
                "id": 3432,
                "uid": None,
                "role": "demandeur",
                "email": "tech.emplois@inclusion.gouv.fr",
                "title": "madame",
                "address": "102 Quai de Jemmapes, 75010 Paris 10ème",
                "last_name": "Test",
                "birth_date": "1969-05-01",
                "birth_name": None,
                "created_at": "2024-08-07T17:01:30.719+02:00",
                "first_name": "Jeanne",
                "phone_number": None,
                "france_travail_id": None,
                "affiliation_number": None,
                "rights_opening_date": None,
                "rdv_solidarites_user_id": 5527,
                "carnet_de_bord_carnet_id": None,
            }
        ],
        "agents": [
            {
                "id": 370,
                "email": "tech.emplois@inclusion.gouv.fr",
                "last_name": "Itou",
                "first_name": "Tech",
                "rdv_solidarites_agent_id": 1791,
            }
        ],
        "status": "unknown",
        "address": "6 Boulevard Saint-Denis, Paris, 75010",
        "starts_at": "2024-08-26T09:00:00.000+02:00",
        "created_by": "user",
        "users_count": 1,
        "cancelled_at": "2024-08-20T09:00:00.000+02:00",
        "organisation": {
            "id": 91,
            "name": "Les Emplois de l'Inclusion",
            "email": None,
            "phone_number": "0102030405",
            "motif_categories": [{"id": 16, "name": "Entretien SIAE", "short_name": "siae_interview"}],
            "department_number": "60",
            "rdv_solidarites_organisation_id": 654,
        },
        "participations": [
            {
                "id": 1174,
                "user": {
                    "id": 3432,
                    "uid": None,
                    "role": "demandeur",
                    "email": "tech.emplois@inclusion.gouv.fr",
                    "title": "madame",
                    "address": "102 Quai de Jemmapes, 75010 Paris 10ème",
                    "last_name": "Test",
                    "birth_date": "1969-05-01",
                    "birth_name": None,
                    "created_at": "2024-08-07T17:01:30.719+02:00",
                    "first_name": "Jeanne",
                    "phone_number": None,
                    "france_travail_id": None,
                    "affiliation_number": None,
                    "rights_opening_date": None,
                    "rdv_solidarites_user_id": 5527,
                    "carnet_de_bord_carnet_id": None,
                },
                "status": "unknown",
                "starts_at": "2024-08-26T09:00:00.000+02:00",
                "created_at": "2024-08-15T19:30:08.719+02:00",
                "created_by": "user",
            }
        ],
        "duration_in_min": 30,
        "max_participants_count": None,
        "rdv_solidarites_rdv_id": 8725,
    },
    "meta": {"event": "created", "model": "Rdv", "timestamp": "2024-08-15 19:30:08 +0200"},
}

RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY_WITHOUT_LIEU = {
    **RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY,
    "data": {**RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY["data"], "lieu": None, "address": ""},
}

RDV_INSERTION_USER_SEARCH_BODY = {
    "user": {
        "id": 1,
        "affiliation_number": "1234567",
        "role": "demandeur",
        "created_at": "2026-09-01T10:00:00.000+02:00",
        "department_internal_id": "8765",
        "first_name": "Camille",
        "last_name": "Martin",
        "title": "madame",
        "address": "12 rue des Lilas 26000 Valence",
        "phone_number": "+33612345678",
        "email": "camille.martin@example.com",
        "birth_date": "1985-03-12",
        "rights_opening_date": None,
        "birth_name": None,
        "rdv_solidarites_user_id": 9876,
        "nir": "285032612345653",
        "france_travail_id": None,
        "referents": [
            {
                "id": 2,
                "email": "claire.durand@drome.fr",
                "first_name": "Claire",
                "last_name": "Durand",
                "rdv_solidarites_agent_id": 42,
            }
        ],
        "tags": [{"id": 1, "value": "Prioritaire"}],
        "follow_ups": [
            {
                "id": 1,
                "created_at": "2026-09-01T10:00:00.000+02:00",
                "status": "rdv_seen",
                "human_status": "RDV honoré",
                "closed_at": None,
                "motif_category": {
                    "id": 1,
                    "short_name": "rsa_orientation",
                    "name": "RSA orientation",
                    "motif_category_type": "rsa_orientation",
                },
                "participations": [
                    {
                        "id": 1,
                        "status": "seen",
                        "created_at": "2026-09-01T10:00:00.000+02:00",
                        "starts_at": "2026-09-15T14:00:00.000+02:00",
                        "created_by": "agent",
                        "rdv": {
                            "id": 1,
                            "duration_in_min": 30,
                            "cancelled_at": None,
                            "address": "5 avenue de la Gare 26000 Valence",
                            "uuid": "2a1f0d7e-6b3c-4c8e-9f11-3d2e5b7a9c10",
                            "created_by": "agent",
                            "status": "seen",
                            "users_count": 1,
                            "max_participants_count": None,
                            "rdv_solidarites_rdv_id": 5555,
                            "starts_at": "2026-09-15T14:00:00.000+02:00",
                            "agents": [
                                {
                                    "id": 2,
                                    "email": "claire.durand@drome.fr",
                                    "first_name": "Claire",
                                    "last_name": "Durand",
                                    "rdv_solidarites_agent_id": 42,
                                }
                            ],
                            "lieu": {
                                "rdv_solidarites_lieu_id": 77,
                                "name": "Maison départementale de Valence",
                                "address": "5 avenue de la Gare 26000 Valence",
                                "phone_number": None,
                            },
                            "motif": {
                                "rdv_solidarites_motif_id": 55,
                                "name": "Rendez-vous d'orientation",
                                "collectif": False,
                                "location_type": "public_office",
                                "follow_up": False,
                                "motif_category": {
                                    "id": 1,
                                    "short_name": "rsa_orientation",
                                    "name": "RSA orientation",
                                    "motif_category_type": "rsa_orientation",
                                },
                            },
                            "organisation": {
                                "id": 1,
                                "name": "Plateforme Insertion Valence",
                                "email": "insertion@drome.fr",
                                "phone_number": "0475000000",
                                "department_number": "26",
                                "rdv_solidarites_organisation_id": 1234,
                                "department_id": 1,
                            },
                        },
                    }
                ],
                "invitations": [
                    {
                        "id": 1,
                        "format": "sms",
                        "clicked": False,
                        "rdv_with_referents": False,
                        "created_at": "2026-09-01T10:00:00.000+02:00",
                        "delivery_status": None,
                        "delivered_at": None,
                        "expires_at": "2026-09-08T10:00:00.000+02:00",
                    }
                ],
            }
        ],
        "organisations": [
            {
                "id": 1,
                "name": "Plateforme Insertion Valence",
                "email": "insertion@drome.fr",
                "phone_number": "0475000000",
                "department_number": "26",
                "rdv_solidarites_organisation_id": 1234,
                "department_id": 1,
                "user_archived_at": None,
            }
        ],
    }
}
