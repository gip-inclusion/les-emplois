from itou.eligibility.models import AdministrativeCriteria
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


TABLE = MetabaseTable(name="critères_iae")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(AdministrativeCriteria, "id"), name="id"),
        get_column_from_field(get_model_field(AdministrativeCriteria, "name"), name="nom"),
        get_column_from_field(get_model_field(AdministrativeCriteria, "level"), name="niveau"),
        get_column_from_field(get_model_field(AdministrativeCriteria, "desc"), name="description"),
    ]
)
