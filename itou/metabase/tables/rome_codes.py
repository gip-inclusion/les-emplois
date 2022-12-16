from itou.metabase.tables.utils import MetabaseTable


TABLE = MetabaseTable(name="codes_rome")
TABLE.add_columns(
    [
        {
            "name": "code_rome",
            "type": "varchar",
            "comment": "Code ROME",
            "fn": lambda o: o.code,
        },
        {
            "name": "description_code_rome",
            "type": "varchar",
            "comment": "Description du code ROME",
            "fn": lambda o: o.name,
        },
    ]
)
