from itou.approvals.models import Suspension
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_model_field,
    hash_content,
)


TABLE = MetabaseTable(name="suspensions")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Suspension, "id"), name="id"),
        {"name": "date_début", "type": "date", "comment": "Date de début", "fn": lambda o: o.start_at},
        {"name": "date_fin", "type": "date", "comment": "Date de fin", "fn": lambda o: o.end_at},
        {
            "name": "created_at",
            "type": "timestamp with time zone",
            "comment": "Date de création",
            "fn": lambda o: o.created_at,
        },
        {"name": "motif", "type": "varchar", "comment": "Motif de suspension", "fn": lambda o: o.reason},
        {
            "name": "hash_numéro_pass_iae",
            "type": "varchar",
            "comment": "Version obfusquée du PASS IAE ou d'agrément",
            "fn": lambda o: hash_content(o.approval.number),
        },
        {
            "name": "en_cours",
            "type": "boolean",
            "comment": "La suspension est en cours",
            "fn": lambda o: o.is_in_progress,
        },
    ]
)
