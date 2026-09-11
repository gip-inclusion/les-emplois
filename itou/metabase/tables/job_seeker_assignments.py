from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.users.models import JobSeekerAssignment


TABLE = MetabaseTable(name="affectations_candidats_v0")
# The free text assignment reason is left out, it may hold personal data.
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(JobSeekerAssignment, "pk"), name="id"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "job_seeker"), name="id_candidat"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "professional"), name="id_accompagnateur"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "company"), name="id_structure"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "prescriber_organization"), name="id_organisation"),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "assigned_to_unknown_advisor"),
            name="accompagnateur_non_référencé",
        ),
        get_column_from_field(get_model_field(JobSeekerAssignment, "last_action_kind"), name="dernière_action"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "last_action_at"), name="date_dernière_action"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "created_at"), name="date_de_création"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "ended_at"), name="date_de_fin"),
        get_column_from_field(get_model_field(JobSeekerAssignment, "end_reason"), name="motif_de_fin"),
    ]
)
