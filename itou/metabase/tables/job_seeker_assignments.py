from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field
from itou.users.enums import ActionKind, AssignmentEndReason
from itou.users.models import JobSeekerAssignment


TABLE = MetabaseTable(name="affectations_candidats_v0")
# The free text assignment reason is left out, it may hold personal data.
TABLE.add_columns(
    [
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "pk"),
            name="id",
            comment="ID de l’accompagnement, c’est-à-dire un professionnel qui suit un candidat",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "job_seeker"),
            name="id_candidat",
            comment="ID C1 du candidat accompagné (candidats_v0.id)",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "professional"),
            name="id_accompagnateur",
            comment="ID C1 du professionnel qui suit le candidat (utilisateurs_v0.id)",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "company"),
            name="id_structure",
            comment=(
                "ID de la structure employeuse au nom de laquelle le professionnel suit le candidat "
                "(structures_v0.id), vide s’il agit pour un prescripteur"
            ),
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "prescriber_organization"),
            name="id_organisation",
            comment=(
                "ID de l’organisation prescriptrice, par exemple une agence France Travail, au nom de laquelle "
                "le professionnel suit le candidat (organisations_v0.id), vide s’il agit pour une structure "
                "employeuse"
            ),
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "assigned_to_unknown_advisor"),
            name="accompagnateur_non_référencé",
            comment="Vrai si l’option « Non référencé sur le service » a été choisie",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "last_action_kind"),
            name="dernière_action",
            comment="Dernière action du professionnel pour le candidat : "
            + ", ".join(f"{kind.value} ({kind.label})" for kind in ActionKind),
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "last_action_at"),
            name="date_dernière_action",
            comment="Date de la dernière action du professionnel pour le candidat",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "created_at"),
            name="date_de_création",
            comment="Date à laquelle le professionnel a commencé à suivre le candidat",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "ended_at"),
            name="date_de_fin",
            comment="Date de fin de l’accompagnement, et non du contrat de travail ; vide tant qu’il est en cours",
        ),
        get_column_from_field(
            get_model_field(JobSeekerAssignment, "end_reason"),
            name="motif_de_fin",
            comment=(
                f"{AssignmentEndReason.MANUAL.value} si un professionnel a clos l’accompagnement, "
                f"{AssignmentEndReason.AUTOMATIC.value} s’il a été clos faute de mise à jour depuis deux ans"
            ),
        ),
    ]
)
