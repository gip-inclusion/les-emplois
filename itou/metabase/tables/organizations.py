from itou.job_applications.enums import Origin, SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_active_siae_pks,
    get_address_columns,
    get_choice,
    get_establishment_is_active_column,
    get_establishment_last_login_date_column,
    get_first_membership_join_date,
)
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User


# Special fake adhoc organization designed to gather stats
# of all prescriber accounts without organization.
# Otherwise organization stats would miss those accounts
# contribution.
# Of course this organization is *never* actually saved in itou's db.
ORG_OF_PRESCRIBERS_WITHOUT_ORG = PrescriberOrganization(
    id=-1, name="Regroupement des prescripteurs sans organisation", kind="SANS-ORGANISATION", is_authorized=False
)


def get_org_first_join_date(org):
    if org != ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return get_first_membership_join_date(memberships=org.prescribermembership_set)
    return None


def get_org_members_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        # Number of prescriber users without org.
        return User.objects.filter(kind=UserKind.PRESCRIBER, prescribermembership=None).count()
    return org.members.count()


def _get_ja_sent_by_prescribers_without_org():
    return JobApplication.objects.filter(
        to_company_id__in=get_active_siae_pks(),
        sender_kind=SenderKind.PRESCRIBER,
        sender_prescriber_organization=None,
    ).exclude(origin=Origin.PE_APPROVAL)


def get_org_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        # Number of job applications made by prescribers without org.
        return _get_ja_sent_by_prescribers_without_org().count()
    return org.job_applications_count


def get_org_accepted_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return _get_ja_sent_by_prescribers_without_org().filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count()
    return org.accepted_job_applications_count


def get_org_last_job_application_creation_date(org):
    if org != ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return org.last_job_application_creation_date
    # This field makes no sense for prescribers without org.
    return None


TABLE = MetabaseTable(name="organisations_v0")
TABLE.add_columns(
    [
        {"name": "id", "type": "integer", "comment": "ID organisation", "fn": lambda o: o.id},
        {"name": "siret", "type": "varchar", "comment": "SIRET organisation", "fn": lambda o: o.siret},
        {"name": "nom", "type": "varchar", "comment": "Nom organisation", "fn": lambda o: o.display_name},
        {
            "name": "type",
            "type": "varchar",
            "comment": "Type organisation (abrégé)",
            "fn": lambda o: o.kind,
        },
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
            "fn": lambda o: o.is_authorized,
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
            "fn": get_org_first_join_date,
        },
        {
            "name": "code_safir",
            "type": "varchar",
            "comment": "Code SAFIR Pôle emploi",
            "fn": lambda o: o.code_safir_pole_emploi,
        },
        {
            "name": "total_membres",
            "type": "integer",
            "comment": "Nombre de comptes prescripteurs rattachés à cette organisation",
            "fn": get_org_members_count,
        },
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Nombre de candidatures émises par cette organisation",
            "fn": get_org_job_applications_count,
        },
        {
            "name": "total_embauches",
            "type": "integer",
            "comment": "Nombre de candidatures en état accepté émises par cette organisation",
            "fn": get_org_accepted_job_applications_count,
        },
        {
            "name": "date_dernière_candidature",
            "type": "date",
            "comment": "Date de la dernière création de candidature",
            "fn": get_org_last_job_application_creation_date,
        },
    ]
)

TABLE.add_columns(get_establishment_last_login_date_column())

TABLE.add_columns(get_establishment_is_active_column())

TABLE.add_columns(
    [
        {
            "name": "brsa",
            "type": "boolean",
            "comment": "Organisation conventionnée pour le suivi des BRSA",
            "fn": lambda o: o.is_brsa,
        },
    ]
)
