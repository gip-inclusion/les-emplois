from itou.analytics.models import DatumCode
from itou.metabase.tables.utils import MetabaseTable


DATUM_CHOICES = dict(DatumCode.choices)


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
        {"name": "type_detail", "type": "varchar", "comment": "Type détaillé", "fn": lambda o: DATUM_CHOICES[o.code]},
    ]
)
