from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria


TABLE = MetabaseTable(name="cap_critères_iae")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(EvaluatedAdministrativeCriteria, "id"), name="id"),
        get_column_from_field(
            get_model_field(EvaluatedAdministrativeCriteria, "administrative_criteria"), name="id_critère_iae"
        ),
        get_column_from_field(
            get_model_field(EvaluatedAdministrativeCriteria, "evaluated_job_application"), name="id_cap_candidature"
        ),
        get_column_from_field(get_model_field(EvaluatedAdministrativeCriteria, "uploaded_at"), name="date_dépôt"),
        get_column_from_field(
            get_model_field(EvaluatedAdministrativeCriteria, "submitted_at"), name="date_transmission"
        ),
        get_column_from_field(get_model_field(EvaluatedAdministrativeCriteria, "review_state"), name="état"),
    ]
)
