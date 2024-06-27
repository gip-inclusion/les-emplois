from itou.job_applications.enums import JobApplicationState
from itou.metabase.tables.job_applications import get_job_application_detailed_origin
from itou.metabase.tables.job_seekers import get_user_signup_kind
from itou.metabase.tables.utils import MetabaseTable, get_choice


UsersTable = MetabaseTable(name="c1_users")
UsersTable.add_columns(
    [
        {
            "name": "id",
            "type": "integer",
            "comment": "ID de l'utilisateur",
            "fn": lambda o: o.pk,
        },
        {
            "name": "type",
            "type": "varchar",
            "comment": "Type d'utilisateur",
            "fn": lambda o: o.kind,
        },
        {
            "name": "date_inscription",
            "type": "date",
            "comment": "Date de création de compte",
            "fn": lambda o: o.date_joined,
        },
        {
            "name": "date_premiere_connexion",
            "type": "date",
            "comment": "Date de première connexion",
            "fn": lambda o: o.first_login,
        },
        {
            "name": "date_dernier_connexion",
            "type": "date",
            "comment": "Date de dernière connexion",
            "fn": lambda o: o.last_login,
        },
        {
            "name": "type_inscription",
            "type": "varchar",
            "comment": "Type inscription du candidat",
            "fn": get_user_signup_kind,
        },
    ]
)


JobApplicationsTable = MetabaseTable(name="c1_job_applications")
JobApplicationsTable.add_columns(
    [
        {
            "name": "id",
            "type": "uuid",
            "comment": "ID C1 de la candidature",
            "fn": lambda o: o.pk,
        },
        {
            "name": "date_candidature",
            "type": "date",
            "comment": "Date de la candidature",
            "fn": lambda o: o.created_at,
        },
        {
            "name": "date_traitement",
            "type": "date",
            "comment": "Date de dernière traitement de la candidature",
            "fn": lambda o: o.processed_at,
        },
        {
            "name": "état",
            "type": "varchar",
            "comment": "Etat de la candidature",
            "fn": lambda o: get_choice(choices=JobApplicationState.choices, key=o.state),
        },
        {
            "name": "motif_de_refus",
            "type": "varchar",
            "comment": "Motif de refus de la candidature",
            "fn": lambda o: o.get_refusal_reason_display() if o.refusal_reason != "" else None,
        },
        {
            "name": "parcours_de_création",
            "type": "varchar",
            "comment": (
                "Parcours de création de la candidature "
                "(Normale, reprise de stock AI, import agrément PE, action support...)"
            ),
            "fn": lambda o: o.origin,
        },
        {
            "name": "origine_détaillée",
            "type": "varchar",
            "comment": (
                "Origine détaillée de la candidature "
                "(employeur EI, ACI... candidat, orienteur, prescripteur PE, ML...)"
            ),
            "fn": get_job_application_detailed_origin,
        },
        {
            "name": "type_structure",
            "type": "varchar",
            "comment": "Type de la structure destinaire de la candidature",
            "fn": lambda o: o.to_company.kind,
        },
    ]
)
