from operator import attrgetter

from itou.metabase.tables.utils import MetabaseTable, get_department_and_region_columns


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
        {
            "name": "recrutement_ouvert",
            "type": "boolean",
            "comment": "Recrutement ouvert à ce jour",
            "fn": attrgetter("is_active"),
        },
        {
            "name": "type_contrat",
            "type": "varchar",
            "comment": "Type de contrat proposé",
            "fn": attrgetter("contract_type"),
        },
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
        {
            "name": "date_création",
            "type": "date",
            "comment": "Date de création",
            "fn": attrgetter("created_at"),
        },
        {
            "name": "date_dernière_modification",
            "type": "date",
            "comment": "Date de dernière modification",
            "fn": attrgetter("updated_at"),
        },
    ]
)
