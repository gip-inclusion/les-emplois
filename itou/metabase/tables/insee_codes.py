from operator import attrgetter

from itou.cities.models import City
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_model_field,
    get_zrr_status_for_insee_code,
)


TABLE = MetabaseTable(name="communes")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(City, "name"), name="nom"),
        get_column_from_field(get_model_field(City, "code_insee"), name="code_insee"),
        {
            "name": "latitude",
            "type": "double precision",
            "comment": "Latitude",
            "fn": attrgetter("latitude"),
        },
        {
            "name": "longitude",
            "type": "double precision",
            "comment": "Longitude",
            "fn": attrgetter("longitude"),
        },
        {
            "name": "statut_zrr",
            "type": "varchar",
            "comment": "Statut ZRR",
            "fn": lambda o: get_zrr_status_for_insee_code(o.code_insee),
        },
    ]
)
