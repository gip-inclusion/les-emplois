from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.siae_evaluations.models import EvaluatedSiae


TABLE = MetabaseTable(name="cap_structures")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(EvaluatedSiae, "id"), name="id"),
        get_column_from_field(get_model_field(EvaluatedSiae, "evaluation_campaign"), name="id_cap_campagne"),
        get_column_from_field(get_model_field(EvaluatedSiae, "siae"), name="id_structure"),
        {
            "name": "état",
            "type": "varchar",
            "comment": "Etat du contrôle de la structure",
            "fn": lambda o: o.state,
        },
        get_column_from_field(get_model_field(EvaluatedSiae, "reviewed_at"), name="date_contrôle"),
        get_column_from_field(get_model_field(EvaluatedSiae, "final_reviewed_at"), name="date_définitive_contrôle"),
    ]
)
