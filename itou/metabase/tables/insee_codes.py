from itou.metabase.tables.utils import MetabaseTable, get_zrr_status_for_insee_code


TABLE = MetabaseTable(name="communes")
TABLE.add_columns(
    [
        {
            "name": "nom",
            "type": "varchar",
            "comment": "Nom",
            "fn": lambda o: o.name,
        },
        {
            "name": "code_insee",
            "type": "varchar",
            "comment": "Code INSEE",
            "fn": lambda o: o.code_insee,
        },
        {
            "name": "latitude",
            "type": "double precision",
            "comment": "Latitude",
            "fn": lambda o: o.latitude,
        },
        {
            "name": "longitude",
            "type": "double precision",
            "comment": "Longitude",
            "fn": lambda o: o.longitude,
        },
        {
            "name": "statut_zrr",
            "type": "varchar",
            "comment": "Statut ZRR",
            "fn": lambda o: get_zrr_status_for_insee_code(o.code_insee),
        },
    ]
)
