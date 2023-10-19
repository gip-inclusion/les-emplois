from itou.companies.models import SiaeJobDescription
from itou.metabase.tables.utils import MetabaseTable, get_department_and_region_columns


def get_field(name):
    return SiaeJobDescription._meta.get_field(name)


TABLE = MetabaseTable(name="fiches_de_poste")

TABLE.add_columns(
    [
        {"name": "id", "type": "integer", "comment": "ID de la fiche de poste", "fn": lambda o: o.id},
        {
            "name": "code_rome",
            "type": "varchar",
            "comment": "Code ROME de la fiche de poste",
            "fn": lambda o: o.appellation.rome.code,
        },
        {
            "name": "nom_rome",
            "type": "varchar",
            "comment": "Nom du ROME de la fiche de poste",
            "fn": lambda o: o.appellation.rome.name,
        },
        {
            "name": "recrutement_ouvert",
            "type": "boolean",
            "comment": "Recrutement ouvert à ce jour",
            "fn": lambda o: o.is_active,
        },
        {"name": "id_employeur", "type": "integer", "comment": "ID employeur", "fn": lambda o: o.siae.id},
        {"name": "type_employeur", "type": "varchar", "comment": "Type employeur", "fn": lambda o: o.siae.kind},
        {"name": "siret_employeur", "type": "varchar", "comment": "SIRET employeur", "fn": lambda o: o.siae.siret},
        {
            "name": "nom_employeur",
            "type": "varchar",
            "comment": "Nom employeur",
            "fn": lambda o: o.siae.display_name,
        },
        {
            "name": "mises_a_jour_champs",
            "type": "jsonb",
            "comment": "historique des mises à jour sur le modèle",
            "fn": lambda o: o.field_history,
        },
    ]
)

TABLE.add_columns(
    get_department_and_region_columns(
        name_suffix="_employeur",
        comment_suffix=" employeur",
        custom_fn=lambda o: o.siae,
    )
)

TABLE.add_columns(
    [
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Total de candidatures reçues",
            "fn": lambda o: o.job_applications_count,
        },
        {
            "name": "date_création",
            "type": "date",
            "comment": "Date de création",
            "fn": lambda o: o.created_at,
        },
        {
            "name": "date_dernière_modification",
            "type": "date",
            "comment": "Date de dernière modification",
            "fn": lambda o: o.updated_at,
        },
    ]
)
