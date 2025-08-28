from itou.analytics.models import Datum, DatumCode, StatsDashboardVisit
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


DATUM_CHOICES = dict(DatumCode.choices)


AnalyticsTable = MetabaseTable(name="c1_analytics_v0")
AnalyticsTable.add_columns(
    [
        # TODO(rsebille): Use get_column_from_field() once it's OK to send an UUID and not a VARCHAR
        {"name": "id", "type": "varchar", "comment": "ID du point de mesure", "fn": lambda o: str(o.pk)},
        get_column_from_field(get_model_field(Datum, "code"), name="type", comment="Type de mesure"),
        get_column_from_field(get_model_field(Datum, "bucket"), name="date", comment="Date associée à la mesure"),
        get_column_from_field(get_model_field(Datum, "value"), name="value", comment="Valeur de la mesure"),
        {"name": "type_detail", "type": "varchar", "comment": "Type détaillé", "fn": lambda o: DATUM_CHOICES[o.code]},
    ]
)

DashboardVisitTable = MetabaseTable(name="c1_private_dashboard_visits_v0")
DashboardVisitTable.add_columns(
    [
        get_column_from_field(get_model_field(StatsDashboardVisit, "pk"), name="id"),
        get_column_from_field(
            get_model_field(StatsDashboardVisit, "measured_at"),
            name="measured_at",
            comment="Date associée à la mesure",
        ),
        # TODO(rsebille): Use get_column_from_field() once it's OK to send an INTEGER and not a VARCHAR
        {
            "name": "dashboard_id",
            "type": "varchar",
            "comment": "ID tableau de bord Metabase",
            "fn": lambda o: str(o.dashboard_id),
        },
        get_column_from_field(get_model_field(StatsDashboardVisit, "department"), name="department"),
        get_column_from_field(get_model_field(StatsDashboardVisit, "region"), name="region"),
        get_column_from_field(get_model_field(StatsDashboardVisit, "current_company_id"), name="current_company_id"),
        get_column_from_field(
            get_model_field(StatsDashboardVisit, "current_prescriber_organization_id"),
            name="current_prescriber_organization_id",
        ),
        get_column_from_field(
            get_model_field(StatsDashboardVisit, "current_institution_id"), name="current_institution_id"
        ),
        get_column_from_field(get_model_field(StatsDashboardVisit, "user_kind"), name="user_kind"),
        get_column_from_field(get_model_field(StatsDashboardVisit, "user_id"), name="user_id"),
    ]
)
