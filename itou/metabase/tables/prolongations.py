from itou.approvals.models import Prolongation
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_common_prolongation_columns


def get_field(name):
    return Prolongation._meta.get_field(name)


TABLE = MetabaseTable(name="prolongations")
TABLE.add_columns(
    get_common_prolongation_columns(get_field_fn=get_field)
    + [
        get_column_from_field(get_field("request_id"), name="id_demande_de_prolongation"),
    ]
)
