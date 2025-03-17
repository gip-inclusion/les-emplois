from itou.approvals.models import Prolongation
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_common_prolongation_columns,
    get_model_field,
)


TABLE = MetabaseTable(name="prolongations")
TABLE.add_columns(
    get_common_prolongation_columns(model=Prolongation)
    + [
        {
            "name": "date_de_création",
            "type": "date",
            "comment": "Date de création",
            "fn": lambda o: o.created_at.date(),
        },
        get_column_from_field(get_model_field(Prolongation, "request"), name="id_demande_de_prolongation"),
    ]
)
