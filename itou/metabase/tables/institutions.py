from itou.institutions.models import Institution
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_department_and_region_columns,
    get_model_field,
)


TABLE = MetabaseTable(name="institutions")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Institution, "id"), name="id"),
        get_column_from_field(get_model_field(Institution, "kind"), name="type"),
    ]
    + get_department_and_region_columns()
    + [
        get_column_from_field(get_model_field(Institution, "name"), name="nom"),
    ]
)
