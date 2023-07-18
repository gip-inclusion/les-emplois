from itou.metabase.tables.utils import MetabaseTable, get_common_prolongation_columns
from itou.approvals.models import Prolongation

def get_field(name):
    return Prolongation._meta.get_field(name)


TABLE = MetabaseTable(name="prolongations")
TABLE.add_columns(
    get_common_prolongation_columns(get_field_fn=get_field)
)
