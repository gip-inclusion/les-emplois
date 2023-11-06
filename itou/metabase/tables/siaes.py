from itou.companies.models import Company
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_address_columns,
    get_choice,
    get_column_from_field,
    get_establishment_is_active_column,
    get_establishment_last_login_date_column,
)


def get_field(name):
    return Company._meta.get_field(name)


TABLE = MetabaseTable(name="structures")
TABLE.add_columns(
    [
        {"name": "id", "type": "integer", "comment": "ID de la structure", "fn": lambda o: o.id},
        {
            "name": "id_asp",
            "type": "integer",
            "comment": "ID de la structure ASP correspondante",
            "fn": lambda o: o.convention.asp_id if o.convention else None,
        },
        {"name": "nom", "type": "varchar", "comment": "Nom de la structure", "fn": lambda o: o.display_name},
        {
            "name": "nom_complet",
            "type": "varchar",
            "comment": "Nom complet de la structure avec type et ID",
            "fn": lambda o: f"{o.kind} - ID {o.id} - {o.display_name}",
        },
        {
            "name": "description",
            "type": "varchar",
            "comment": "Description de la structure",
            "fn": lambda o: o.description,
        },
        {
            "name": "type",
            "type": "varchar",
            "comment": "Type de structure (EI, ETTI, ACI, GEIQ etc..)",
            "fn": lambda o: o.kind,
        },
        {"name": "siret", "type": "varchar", "comment": "SIRET de la structure", "fn": lambda o: o.siret},
        {
            "name": "source",
            "type": "varchar",
            "comment": "Source des données de la structure",
            "fn": lambda o: get_choice(choices=Company.SOURCE_CHOICES, key=o.source),
        },
        get_column_from_field(get_field("naf"), name="code_naf"),
        get_column_from_field(get_field("email"), name="email_public"),
        get_column_from_field(get_field("auth_email"), name="email_authentification"),
    ]
)


def get_parent_siae(siae):
    if siae.convention_id and siae.source == Company.SOURCE_USER_CREATED:
        # NOTE: siae.convention.siaes should absolutely be prefetched !
        for convention_siae in siae.convention.siaes.all():
            if convention_siae.source == Company.SOURCE_ASP:
                return convention_siae
    return siae


TABLE.add_columns(get_address_columns(comment_suffix=" de la structure mère", custom_fn=get_parent_siae))
TABLE.add_columns(get_address_columns(name_suffix="_c1", comment_suffix=" de la structure C1"))

TABLE.add_columns(
    [
        {
            "name": "date_inscription",
            "type": "date",
            "comment": "Date inscription du premier compte employeur",
            "fn": lambda o: o.first_membership_join_date,
        },
        {
            "name": "total_membres",
            "type": "integer",
            "comment": "Nombre de comptes employeur rattachés à la structure",
            "fn": lambda o: o.members.count(),
        },
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Nombre de candidatures dont la structure est destinataire",
            "fn": lambda o: o.total_candidatures,
        },
        {
            "name": "total_candidatures_30j",
            "type": "integer",
            "comment": "Nombre de candidatures dans les 30 jours glissants dont la structure est destinataire",
            "fn": lambda o: o.total_candidatures_30j,
        },
        {
            "name": "total_embauches",
            "type": "integer",
            "comment": "Nombre de candidatures en état accepté dont la structure est destinataire",
            "fn": lambda o: o.total_embauches,
        },
        {
            "name": "total_embauches_30j",
            "type": "integer",
            "comment": (
                "Nombre de candidatures en état accepté dans les 30 jours glissants "
                "dont la structure est destinataire"
            ),
            "fn": lambda o: o.total_embauches_30j,
        },
        {
            "name": "taux_conversion_30j",
            "type": "double precision",
            "comment": "Taux de conversion des candidatures en embauches dans les 30 jours glissants",
            "fn": lambda o: round(
                1.0 * o.total_embauches_30j / o.total_candidatures_30j if o.total_candidatures_30j else 0.0,
                2,
            ),
        },
        # FIXME(vperron) Sur ce cas précis ça vaudrait le coup d'exporter chaque jour le contenu de la table
        # plutot que de s'écrire des agrégations à l'infini
        {
            "name": "total_auto_prescriptions",
            "type": "integer",
            "comment": "Nombre de candidatures de source employeur dont la structure est destinataire",
            "fn": lambda o: o.total_auto_prescriptions,
        },
        {
            "name": "total_candidatures_autonomes",
            "type": "integer",
            "comment": "Nombre de candidatures de source candidat dont la structure est destinataire",
            "fn": lambda o: o.total_candidatures_autonomes,
        },
        {
            "name": "total_candidatures_via_prescripteur",
            "type": "integer",
            "comment": "Nombre de candidatures de source prescripteur dont la structure est destinataire",
            "fn": lambda o: o.total_candidatures_prescripteur,
        },
        {
            "name": "total_candidatures_non_traitées",
            "type": "integer",
            "comment": "Nombre de candidatures en état nouveau dont la structure est destinataire",
            "fn": lambda o: o.total_candidatures_non_traitees,
        },
        {
            "name": "total_candidatures_en_étude",
            "type": "integer",
            "comment": "Nombre de candidatures en état étude dont la structure est destinataire",
            "fn": lambda o: o.total_candidatures_en_cours,
        },
    ]
)

TABLE.add_columns(get_establishment_last_login_date_column())

TABLE.add_columns(get_establishment_is_active_column())

TABLE.add_columns(
    [
        {
            "name": "date_dernière_évolution_candidature",
            "type": "date",
            "comment": "Date de dernière évolution candidature sauf passage obsolète",
            "fn": lambda o: o.last_job_application_transition_date,
        },
        {
            "name": "total_fiches_de_poste_actives",
            "type": "integer",
            "comment": "Nombre de fiches de poste actives de la structure",
            "fn": lambda o: len([jd for jd in o.job_description_through.all() if jd.is_active]),
        },
        {
            "name": "total_fiches_de_poste_inactives",
            "type": "integer",
            "comment": "Nombre de fiches de poste inactives de la structure",
            "fn": lambda o: len([jd for jd in o.job_description_through.all() if not jd.is_active]),
        },
    ]
)
