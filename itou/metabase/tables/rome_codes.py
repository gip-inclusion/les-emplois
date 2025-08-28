from itou.jobs.models import Rome
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


TABLE = MetabaseTable(name="codes_rome")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Rome, "code"), name="code_rome"),
        get_column_from_field(get_model_field(Rome, "name"), name="description_code_rome"),
    ]
)
