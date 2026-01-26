from operator import attrgetter

from itou.companies.enums import CompanySource
from itou.companies.models import Company
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_address_columns,
    get_choice,
    get_column_from_field,
    get_establishment_is_active_column,
    get_establishment_last_login_date_column,
    get_model_field,
)


TABLE = MetabaseTable(name="structures_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Company, "pk"), name="id"),
        {
            "name": "id_asp",
            "type": "integer",
            "comment": "ID de la structure ASP correspondante",
            "fn": lambda o: o.convention.asp_id if o.convention else None,
        },
        {"name": "nom", "type": "varchar", "comment": "Nom de la structure", "fn": attrgetter("display_name")},
        {
            "name": "nom_complet",
            "type": "varchar",
            "comment": "Nom complet de la structure avec type et ID",
            "fn": lambda o: f"{o.kind} - ID {o.id} - {o.display_name}",
        },
        get_column_from_field(get_model_field(Company, "description"), name="description"),
        get_column_from_field(get_model_field(Company, "kind"), name="type"),
        get_column_from_field(get_model_field(Company, "siret"), name="siret"),
        {
            "name": "source",
            "type": "varchar",
            "comment": "Source des données de la structure",
            "fn": lambda o: get_choice(choices=CompanySource.choices, key=o.source),
        },
        get_column_from_field(get_model_field(Company, "naf"), name="code_naf"),
        get_column_from_field(get_model_field(Company, "email"), name="email_public"),
        get_column_from_field(get_model_field(Company, "auth_email"), name="email_authentification"),
        {
            "name": "convergence_france",
            "type": "boolean",
            "comment": "Convergence France (contrats PHC et CVG)",
            "fn": attrgetter("is_aci_convergence"),
        },
    ]
)

TABLE.add_columns(
    get_address_columns(comment_suffix=" de la structure mère", custom_fn=(lambda o: o.canonical_company))
)
TABLE.add_columns(get_address_columns(name_suffix="_c1", comment_suffix=" de la structure C1"))

TABLE.add_columns(
    [
        {
            "name": "date_inscription",
            "type": "date",
            "comment": "Date inscription du premier compte employeur",
            "fn": attrgetter("first_membership_join_date"),
        },
        {
            "name": "total_membres",
            "type": "integer",
            "comment": "Nombre de comptes employeur rattachés à la structure",
            "fn": lambda o: o.active_memberships_count or 0,
        },
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Nombre de candidatures dont la structure est destinataire",
            "fn": attrgetter("total_candidatures"),
        },
        {
            "name": "total_candidatures_30j",
            "type": "integer",
            "comment": "Nombre de candidatures dans les 30 jours glissants dont la structure est destinataire",
            "fn": attrgetter("total_candidatures_30j"),
        },
        {
            "name": "total_embauches",
            "type": "integer",
            "comment": "Nombre de candidatures en état accepté dont la structure est destinataire",
            "fn": attrgetter("total_embauches"),
        },
        {
            "name": "total_embauches_30j",
            "type": "integer",
            "comment": (
                "Nombre de candidatures en état accepté dans les 30 jours glissants dont la structure est destinataire"
            ),
            "fn": attrgetter("total_embauches_30j"),
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
            "fn": attrgetter("total_auto_prescriptions"),
        },
        {
            "name": "total_candidatures_autonomes",
            "type": "integer",
            "comment": "Nombre de candidatures de source candidat dont la structure est destinataire",
            "fn": attrgetter("total_candidatures_autonomes"),
        },
        {
            "name": "total_candidatures_via_prescripteur",
            "type": "integer",
            "comment": "Nombre de candidatures de source prescripteur dont la structure est destinataire",
            "fn": attrgetter("total_candidatures_prescripteur"),
        },
        {
            "name": "total_candidatures_non_traitées",
            "type": "integer",
            "comment": "Nombre de candidatures en état nouveau dont la structure est destinataire",
            "fn": attrgetter("total_candidatures_non_traitees"),
        },
        {
            "name": "total_candidatures_en_étude",
            "type": "integer",
            "comment": "Nombre de candidatures en état étude dont la structure est destinataire",
            "fn": attrgetter("total_candidatures_en_cours"),
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
            "fn": attrgetter("last_job_application_transition_date"),
        },
        {
            "name": "total_fiches_de_poste_actives",
            "type": "integer",
            "comment": "Nombre de fiches de poste actives de la structure",
            "fn": lambda o: o.job_descriptions_active_count or 0,
        },
        {
            "name": "total_fiches_de_poste_inactives",
            "type": "integer",
            "comment": "Nombre de fiches de poste inactives de la structure",
            "fn": lambda o: o.job_descriptions_inactive_count or 0,
        },
    ]
)
