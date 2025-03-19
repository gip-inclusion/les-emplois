from itou.approvals.models import Suspension
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_model_field,
)


TABLE = MetabaseTable(name="suspensions_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Suspension, "id"), name="id"),
        get_column_from_field(get_model_field(Suspension, "approval"), name="id_pass_agrément"),
        get_column_from_field(get_model_field(Suspension, "start_at"), name="date_début"),
        get_column_from_field(get_model_field(Suspension, "end_at"), name="date_fin"),
        get_column_from_field(get_model_field(Suspension, "reason"), name="motif"),
        {
            "name": "en_cours",
            "type": "boolean",
            "comment": "La suspension est en cours",
            "fn": lambda o: o.is_in_progress,
        },
        get_column_from_field(get_model_field(Suspension, "created_at"), name="date_de_création"),
    ]
)
