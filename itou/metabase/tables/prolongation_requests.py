from itou.metabase.tables.utils import MetabaseTable, get_common_prolongation_columns
from itou.approvals.models import ProlongationRequest

def get_field(name):
    return ProlongationRequest._meta.get_field(name)


TABLE = MetabaseTable(name="demandes_de_prolongation")
TABLE.add_columns(
    get_common_prolongation_columns(get_field_fn=get_field)
)
