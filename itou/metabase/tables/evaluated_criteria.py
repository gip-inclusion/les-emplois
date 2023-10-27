from itou.metabase.tables.utils import MetabaseTable, get_column_from_field
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria


def get_field(name):
    return EvaluatedAdministrativeCriteria._meta.get_field(name)


TABLE = MetabaseTable(name="cap_critères_iae")
TABLE.add_columns(
    [
        get_column_from_field(get_field("id"), name="id"),
        get_column_from_field(get_field("administrative_criteria"), name="id_critère_iae"),
        get_column_from_field(get_field("evaluated_job_application"), name="id_cap_candidature"),
        get_column_from_field(get_field("uploaded_at"), name="date_dépôt"),
        get_column_from_field(get_field("submitted_at"), name="date_transmission"),
        get_column_from_field(get_field("review_state"), name="état"),
    ]
)
