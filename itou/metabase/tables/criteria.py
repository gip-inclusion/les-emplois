from itou.eligibility.models import AdministrativeCriteria
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field


def get_field(name):
    return AdministrativeCriteria._meta.get_field(name)


TABLE = MetabaseTable(name="critères_iae")
TABLE.add_columns(
    [
        get_column_from_field(get_field("id"), name="id"),
        get_column_from_field(get_field("name"), name="nom"),
        get_column_from_field(get_field("level"), name="niveau"),
        get_column_from_field(get_field("desc"), name="description"),
    ]
)
