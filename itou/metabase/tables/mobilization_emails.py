from itou.insertion.models import MobilizationEmail
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER


def get_user_kind(mobilization_email):
    PREFIX = "emplois_"
    if mobilization_email.sender_prescriber_organization_id is not None:
        return PREFIX + KIND_PRESCRIBER
    elif mobilization_email.sender_company_id is not None:
        return PREFIX + KIND_EMPLOYER
    # This should not happen thanks to the DB constraint
    return None


TABLE = MetabaseTable(name="mer_mail_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(MobilizationEmail, "pk"), "id"),
        get_column_from_field(
            get_model_field(MobilizationEmail, "sent_at"),
            name="sent_at",
            comment="date d’envoi du mail par le prescripteur",
        ),
        get_column_from_field(
            get_model_field(MobilizationEmail, "answered_at"),
            name="answered_at",
            comment="date de réception de la réponse de l’offreur de service",
        ),
        {"name": "user_kind", "type": "varchar", "comment": "Type d’utilisateur", "fn": get_user_kind},
        get_column_from_field(get_model_field(MobilizationEmail, "sender"), name="user_id"),
        get_column_from_field(
            get_model_field(MobilizationEmail, "sender_prescriber_organization"),
            name="user_prescriber_organization_id",
        ),
        get_column_from_field(get_model_field(MobilizationEmail, "sender_company"), name="user_company_id"),
        get_column_from_field(
            get_model_field(MobilizationEmail, "mobilization_event"),
            name="imer_id",
            comment="ID de l’iMER enregistrée au clic sur 'Voir les coordonnées'",
        ),
        {
            "name": "service_id",
            "type": "varchar",
            "comment": "UID du service",
            "fn": lambda o: o.service.uid if o.service else None,
        },
    ]
)
