from operator import attrgetter

from itou.metabase.tables.utils import MetabaseTable, get_zrr_status_for_insee_code


TABLE = MetabaseTable(name="communes")
TABLE.add_columns(
    [
        {
            "name": "nom",
            "type": "varchar",
            "comment": "Nom",
            "fn": attrgetter("name"),
        },
        {
            "name": "code_insee",
            "type": "varchar",
            "comment": "Code INSEE",
            "fn": attrgetter("code_insee"),
        },
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
