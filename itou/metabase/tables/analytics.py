from itou.analytics.models import DatumCode
from itou.metabase.tables.utils import MetabaseTable


DATUM_CHOICES = dict(DatumCode.choices)


AnalyticsTable = MetabaseTable(name="c1_analytics_v0")
AnalyticsTable.add_columns(
    [
        {"name": "id", "type": "varchar", "comment": "ID du point de mesure", "fn": lambda o: str(o.pk)},
        {
            "name": "type",
            "type": "varchar",
            "comment": "Type de mesure",
            "fn": lambda o: o.code,
        },
        {
            "name": "date",
            "type": "varchar",
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

DashboardVisitTable = MetabaseTable(name="c1_private_dashboard_visits_v0")
DashboardVisitTable.add_columns(
    [
        {"name": "id", "type": "integer", "comment": "ID du point de mesure", "fn": lambda o: o.pk},
        {
            "name": "measured_at",
            "type": "timestamp with time zone",  # which is UTC
            "fn": lambda o: o.measured_at,
            "comment": "Date associée à la mesure",
        },
        {
            "name": "dashboard_id",
            "type": "varchar",
            "comment": "ID tableau de bord Metabase",
            "fn": lambda o: str(o.dashboard_id),
        },
        {
            "name": "department",
            "type": "varchar",
            "comment": "Département",
            "fn": lambda o: o.department,
        },
        {
            "name": "region",
            "type": "varchar",
            "comment": "Région",
            "fn": lambda o: o.region,
        },
        {
            "name": "current_company_id",
            "type": "integer",
            "comment": "ID entreprise courante",
            "fn": lambda o: o.current_company_id,
        },
        {
            "name": "current_prescriber_organization_id",
            "type": "integer",
            "comment": "ID organisation prescriptrice courante",
            "fn": lambda o: o.current_prescriber_organization_id,
        },
        {
            "name": "current_institution_id",
            "type": "integer",
            "comment": "ID institution courante",
            "fn": lambda o: o.current_institution_id,
        },
        {
            "name": "user_kind",
            "type": "varchar",
            "comment": "Type utilisateur",
            "fn": lambda o: o.user_kind,
        },
        {
            "name": "user_id",
            "type": "integer",
            "comment": "ID utilisateur",
            "fn": lambda o: o.user_id,
        },
    ]
)
