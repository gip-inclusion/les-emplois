from itou.metabase.tables.utils import MetabaseTable


AnalyticsTable = MetabaseTable(name="c1_analytics_v0")
AnalyticsTable.add_columns(
    [
        {"name": "id", "type": "varchar", "comment": "ID du point de mesure", "fn": lambda o: o.pk},
        {
            "name": "type",
            "type": "varchar",
            "comment": "Type de mesure",
            "fn": lambda o: o.code,
        },
        {
            "name": "date",
            "type": "date",
            "comment": "Date associée à la mesure",
            "fn": lambda o: o.bucket,
        },
        {
            "name": "value",
            "type": "integer",
            "comment": "Valeur de la mesure",
            "fn": lambda o: o.value,
        },
    ]
)
