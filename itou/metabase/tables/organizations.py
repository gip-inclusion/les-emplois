from operator import attrgetter

from itou.metabase.tables.utils import (
    MetabaseTable,
    get_address_columns,
    get_choice,
    get_column_from_field,
    get_establishment_is_active_column,
    get_establishment_last_login_date_column,
    get_model_field,
)
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization


TABLE = MetabaseTable(name="organisations_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(PrescriberOrganization, "pk"), name="id"),
        get_column_from_field(get_model_field(PrescriberOrganization, "siret"), name="siret"),
        {"name": "nom", "type": "varchar", "comment": "Nom organisation", "fn": attrgetter("display_name")},
        get_column_from_field(
            get_model_field(PrescriberOrganization, "kind"), name="type", comment="Type organisation (abrégé)"
        ),
        {
            "name": "type_complet",
            "type": "varchar",
            "comment": "Type organisation (détaillé)",
            "fn": lambda o: get_choice(choices=PrescriberOrganizationKind.choices, key=o.kind),
        },
        {
            "name": "habilitée",
            "type": "boolean",
            "comment": "Organisation habilitée",
            "fn": attrgetter("is_authorized"),
        },
    ]
)

TABLE.add_columns(get_address_columns(comment_suffix=" de cette organisation"))

TABLE.add_columns(
    [
        {
            "name": "date_inscription",
            "type": "date",
            "comment": "Date inscription du premier compte prescripteur",
            "fn": attrgetter("first_membership_join_date"),
        },
        get_column_from_field(get_model_field(PrescriberOrganization, "code_safir_pole_emploi"), name="code_safir"),
        {
            "name": "total_membres",
            "type": "integer",
            "comment": "Nombre de comptes prescripteurs rattachés à cette organisation",
            "fn": lambda org: org.active_memberships_count or 0,
        },
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Nombre de candidatures émises par cette organisation",
            "fn": attrgetter("job_applications_count"),
        },
        {
            "name": "total_embauches",
            "type": "integer",
            "comment": "Nombre de candidatures en état accepté émises par cette organisation",
            "fn": attrgetter("accepted_job_applications_count"),
        },
        {
            "name": "date_dernière_candidature",
            "type": "date",
            "comment": "Date de la dernière création de candidature",
            "fn": attrgetter("last_job_application_creation_date"),
        },
    ]
)

TABLE.add_columns(get_establishment_last_login_date_column())
TABLE.add_columns(get_establishment_is_active_column())


TABLE.add_columns(
    [
        get_column_from_field(get_model_field(PrescriberOrganization, "is_brsa"), name="brsa"),
    ]
)
