from itou.institutions.models import Institution
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_department_and_region_columns


def get_field(name):
    return Institution._meta.get_field(name)


TABLE = MetabaseTable(name="institutions")
TABLE.add_columns(
    [
        get_column_from_field(get_field("id"), name="id"),
        get_column_from_field(get_field("kind"), name="type"),
    ]
    + get_department_and_region_columns()
    + [
        get_column_from_field(get_field("name"), name="nom"),
    ]
)
