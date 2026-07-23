from itou.insertion.models import MobilizationEvent
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER


def get_user_kind(mobilization_event):
    PREFIX = "emplois_"
    if mobilization_event.user_id is None:
        return PREFIX + "anonymous"
    elif mobilization_event.prescriber_organization_id is not None:
        return PREFIX + KIND_PRESCRIBER
    elif mobilization_event.company_id is not None:
        return PREFIX + KIND_EMPLOYER


TABLE = MetabaseTable(name="imer_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(MobilizationEvent, "pk"), "id"),
        get_column_from_field(get_model_field(MobilizationEvent, "created_at"), name="date"),
        get_column_from_field(get_model_field(MobilizationEvent, "session_key"), name="user_session"),
        {"name": "user_kind", "type": "varchar", "comment": "Type d’utilisateur", "fn": get_user_kind},
        get_column_from_field(get_model_field(MobilizationEvent, "user"), name="user_id"),
        get_column_from_field(
            get_model_field(MobilizationEvent, "prescriber_organization"), name="user_prescriber_organization_id"
        ),
        get_column_from_field(get_model_field(MobilizationEvent, "company"), name="user_company_id"),
        {
            "name": "structure_id",
            "type": "varchar",
            "comment": "UID de la structure",
            "fn": lambda o: o.structure.uid,
        },
        get_column_from_field(get_model_field(MobilizationEvent, "kind"), name="kind"),
        {
            "name": "service_id",
            "type": "varchar",
            "comment": "UID du service",
            "fn": lambda o: o.service.uid if o.service else None,
        },
        {
            "name": "source",
            "type": "varchar",
            "comment": "source",
            "fn": lambda o: o.structure.source.value,
        },
        get_column_from_field(get_model_field(MobilizationEvent, "service_external_link"), name="external_link"),
        {
            "name": "orientation_id",
            "type": "varchar",
            "comment": "ID de l’éventuelle orientation",
            "fn": lambda o: str(o.orientation_id) if o.orientation_id else None,
        },
    ]
)
