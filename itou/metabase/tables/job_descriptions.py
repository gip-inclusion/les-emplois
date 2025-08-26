from operator import attrgetter

from itou.companies.models import JobDescription
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_department_and_region_columns,
    get_model_field,
)


TABLE = MetabaseTable(name="fiches_de_poste")

TABLE.add_columns(
    [
        {"name": "id", "type": "integer", "comment": "ID de la fiche de poste", "fn": attrgetter("id")},
        {
            "name": "code_rome",
            "type": "varchar",
            "comment": "Code ROME de la fiche de poste",
            "fn": attrgetter("appellation.rome.code"),
        },
        {
            "name": "nom_rome",
            "type": "varchar",
            "comment": "Nom du ROME de la fiche de poste",
            "fn": attrgetter("appellation.rome.name"),
        },
        get_column_from_field(get_model_field(JobDescription, "is_active"), name="recrutement_ouvert"),
        get_column_from_field(get_model_field(JobDescription, "contract_type"), name="type_contrat"),
        {"name": "id_employeur", "type": "integer", "comment": "ID employeur", "fn": attrgetter("company.id")},
        {"name": "type_employeur", "type": "varchar", "comment": "Type employeur", "fn": attrgetter("company.kind")},
        {
            "name": "siret_employeur",
            "type": "varchar",
            "comment": "SIRET employeur",
            "fn": attrgetter("company.siret"),
        },
        {
            "name": "nom_employeur",
            "type": "varchar",
            "comment": "Nom employeur",
            "fn": attrgetter("company.display_name"),
        },
        {
            "name": "mises_a_jour_champs",
            "type": "jsonb",
            "comment": "historique des mises à jour sur le modèle",
            "fn": attrgetter("field_history"),
        },
    ]
)

TABLE.add_columns(
    get_department_and_region_columns(
        name_suffix="_employeur",
        comment_suffix=" employeur",
        custom_fn=attrgetter("company"),
    )
)

TABLE.add_columns(
    [
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Total de candidatures reçues",
            "fn": attrgetter("job_applications_count"),
        },
        get_column_from_field(get_model_field(JobDescription, "created_at"), name="date_création", field_type="date"),
        get_column_from_field(
            get_model_field(JobDescription, "updated_at"), name="date_dernière_modification", field_type="date"
        ),
    ]
)
