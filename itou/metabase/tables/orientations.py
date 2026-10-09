from itou.insertion.models import Orientation
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


SENDER_KIND_PREFIX = "emplois_"

TABLE = MetabaseTable(name="orientations_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Orientation, "pk"), name="id"),
        get_column_from_field(get_model_field(Orientation, "created_at"), name="creation_date"),
        get_column_from_field(get_model_field(Orientation, "processing_date"), name="processing_date"),
        {
            "name": "status",
            "type": "varchar",
            "comment": "Statut de l’orientation",
            "fn": lambda o: str(o.status),
        },
        {
            "name": "service_uid",
            "type": "varchar",
            "comment": "ID DI du service",
            "fn": lambda o: o.service.uid if o.service else None,
        },
        {
            "name": "structure_uid",
            "type": "varchar",
            "comment": "ID DI de la structure",
            "fn": lambda o: o.service.structure.uid,
        },
        get_column_from_field(
            get_model_field(Orientation, "beneficiary_id"), name="beneficiary_id", comment="ID C1 du bénéficiaire"
        ),
        {
            "name": "beneficiary_public_id",
            "type": "uuid",
            "comment": "ID public du bénéficiaire",
            "fn": lambda o: o.beneficiary.public_id,
        },
        get_column_from_field(
            get_model_field(Orientation, "sender_id"),
            name="sender_id",
            comment="ID C1 du prescripteur (employeur ou prescripteur)",
        ),
        {
            "name": "sender_public_id",
            "type": "uuid",
            "comment": "ID public du prescripteur (employeur ou prescripteur)",
            "fn": lambda o: o.sender.public_id,
        },
        {
            "name": "sender_kind",
            "type": "varchar",
            "comment": "Type d’utilisateur",
            "fn": lambda o: SENDER_KIND_PREFIX + o.sender_kind,
        },
        get_column_from_field(
            get_model_field(Orientation, "sender_prescriber_organization_id"),
            name="sender_prescriber_organization_id",
            comment="ID C1 de l’organisation prescriptrice émettrice",
        ),
        {
            "name": "sender_prescriber_organization_public_id",
            "type": "uuid",
            "comment": "ID public de l’organisation prescriptrice émettrice",
            "fn": lambda o: o.sender_prescriber_organization.uid if o.sender_prescriber_organization else None,
        },
        get_column_from_field(
            get_model_field(Orientation, "sender_company_id"),
            name="sender_company_id",
            comment="ID C1 de l’entreprise émettrice",
        ),
        {
            "name": "sender_company_public_id",
            "type": "uuid",
            "comment": "ID public de l’entreprise émettrice",
            "fn": lambda o: o.sender_company.uid if o.sender_company else None,
        },
        get_column_from_field(
            get_model_field(Orientation, "data_protection_commitment"), name="data_protection_commitment"
        ),
        get_column_from_field(
            get_model_field(Orientation, "last_reminder_email_sent_at"), name="last_reminder_email_sent_at"
        ),
    ]
)
