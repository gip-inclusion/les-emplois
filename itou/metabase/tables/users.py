from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.users.models import User


TABLE = MetabaseTable(name="utilisateurs_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(User, "id"), name="id"),
        get_column_from_field(get_model_field(User, "email"), name="email"),
        get_column_from_field(get_model_field(User, "kind"), name="type"),
        get_column_from_field(get_model_field(User, "first_name"), name="prenom"),
        get_column_from_field(get_model_field(User, "last_name"), name="nom"),
    ]
)
