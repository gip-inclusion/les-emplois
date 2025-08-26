from operator import attrgetter

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
            "fn": attrgetter("code"),
        },
        {
            "name": "date",
            "type": "varchar",
            "comment": "Date associée à la mesure",
            "fn": attrgetter("bucket"),
        },
        {
            "name": "value",
            "type": "integer",
            "comment": "Valeur de la mesure",
            "fn": attrgetter("value"),
        },
        {"name": "type_detail", "type": "varchar", "comment": "Type détaillé", "fn": lambda o: DATUM_CHOICES[o.code]},
    ]
)

DashboardVisitTable = MetabaseTable(name="c1_private_dashboard_visits_v0")
DashboardVisitTable.add_columns(
    [
        {"name": "id", "type": "integer", "comment": "ID du point de mesure", "fn": attrgetter("pk")},
        {
            "name": "measured_at",
            "type": "timestamp with time zone",  # which is UTC
            "fn": attrgetter("measured_at"),
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
            "fn": attrgetter("department"),
        },
        {
            "name": "region",
            "type": "varchar",
            "comment": "Région",
            "fn": attrgetter("region"),
        },
        {
            "name": "current_company_id",
            "type": "integer",
            "comment": "ID entreprise courante",
            "fn": attrgetter("current_company_id"),
        },
        {
            "name": "current_prescriber_organization_id",
            "type": "integer",
            "comment": "ID organisation prescriptrice courante",
            "fn": attrgetter("current_prescriber_organization_id"),
        },
        {
            "name": "current_institution_id",
            "type": "integer",
            "comment": "ID institution courante",
            "fn": attrgetter("current_institution_id"),
        },
        {
            "name": "user_kind",
            "type": "varchar",
            "comment": "Type utilisateur",
            "fn": attrgetter("user_kind"),
        },
        {
            "name": "user_id",
            "type": "integer",
            "comment": "ID utilisateur",
            "fn": attrgetter("user_id"),
        },
    ]
)
