from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.siae_evaluations.models import EvaluatedJobApplication


TABLE = MetabaseTable(name="cap_candidatures")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(EvaluatedJobApplication, "id"), name="id"),
        get_column_from_field(get_model_field(EvaluatedJobApplication, "job_application"), name="id_candidature"),
        get_column_from_field(get_model_field(EvaluatedJobApplication, "evaluated_siae"), name="id_cap_structure"),
        {
            "name": "état",
            "type": "varchar",
            "comment": "Etat du contrôle de la candidature",
            "fn": lambda o: o.compute_state(),
        },
    ]
)
