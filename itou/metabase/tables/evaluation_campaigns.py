from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.siae_evaluations.models import EvaluationCampaign


TABLE = MetabaseTable(name="cap_campagnes")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(EvaluationCampaign, "id"), name="id"),
        get_column_from_field(get_model_field(EvaluationCampaign, "name"), name="nom"),
        get_column_from_field(get_model_field(EvaluationCampaign, "institution"), name="id_institution"),
        get_column_from_field(get_model_field(EvaluationCampaign, "evaluated_period_start_at"), name="date_début"),
        get_column_from_field(get_model_field(EvaluationCampaign, "evaluated_period_end_at"), name="date_fin"),
        get_column_from_field(get_model_field(EvaluationCampaign, "chosen_percent"), name="pourcentage_sélection"),
    ]
)
