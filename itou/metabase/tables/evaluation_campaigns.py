from itou.metabase.tables.utils import MetabaseTable, get_column_from_field
from itou.siae_evaluations.models import EvaluationCampaign


def get_field(name):
    return EvaluationCampaign._meta.get_field(name)


TABLE = MetabaseTable(name="cap_campagnes")
TABLE.add_columns(
    [
        get_column_from_field(get_field("id"), name="id"),
        get_column_from_field(get_field("name"), name="nom"),
        get_column_from_field(get_field("institution"), name="id_institution"),
        get_column_from_field(get_field("evaluated_period_start_at"), name="date_début"),
        get_column_from_field(get_field("evaluated_period_end_at"), name="date_fin"),
        get_column_from_field(get_field("chosen_percent"), name="pourcentage_sélection"),
    ]
)
