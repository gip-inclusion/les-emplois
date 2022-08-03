from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.management.commands._utils import (
    get_active_siae_pks,
    get_address_columns,
    get_choice,
    get_establishment_is_active_column,
    get_establishment_last_login_date_column,
    get_first_membership_join_date,
)
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
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
        return User.objects.filter(is_prescriber=True, prescribermembership=None).count()
    return org.members.count()


def _get_ja_sent_by_prescribers_without_org():
    return JobApplication.objects.filter(
        created_from_pe_approval=False,
        to_siae_id__in=get_active_siae_pks(),
        sender_kind=SenderKind.PRESCRIBER,
        sender_prescriber_organization=None,
    )


def _get_org_job_applications(org):
    job_applications = list(org.jobapplication_set.all())
    # We have to do all this in python to benefit from prefetch_related.
    job_applications = [
        ja
        for ja in job_applications
        if ja.created_from_pe_approval is False and ja.to_siae_id in get_active_siae_pks()
    ]
    return job_applications


def get_org_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        # Number of job applications made by prescribers without org.
        return _get_ja_sent_by_prescribers_without_org().count()
    return len(_get_org_job_applications(org))


def get_org_accepted_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return _get_ja_sent_by_prescribers_without_org().filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count()
    job_applications = [
        ja for ja in _get_org_job_applications(org) if ja.state == JobApplicationWorkflow.STATE_ACCEPTED
    ]
    return len(job_applications)


def get_org_last_job_application_creation_date(org):
    if org != ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        job_applications = _get_org_job_applications(org)
        # We have to do all this in python to benefit from prefetch_related.
        if len(job_applications) >= 1:
            job_applications.sort(key=lambda o: o.created_at, reverse=True)
            last_job_application = job_applications[0]
            return last_job_application.created_at
    # This field makes no sense for prescribers without org.
    return None


ORGANIZATION_KIND_TO_READABLE_KIND = {
    PrescriberOrganizationKind.PE: "Pôle emploi",
    PrescriberOrganizationKind.CAP_EMPLOI: "CAP emploi",
    PrescriberOrganizationKind.ML: "Mission locale",
    PrescriberOrganizationKind.DEPT: "Département",
    PrescriberOrganizationKind.OTHER: "Autre",
}

TABLE_COLUMNS = [
    {"name": "id", "type": "integer", "comment": "ID organisation", "fn": lambda o: o.id},
    {"name": "nom", "type": "varchar", "comment": "Nom organisation", "fn": lambda o: o.display_name},
    {
        "name": "type",
        "type": "varchar",
        "comment": "Type organisation (abrégé)",
        "fn": lambda o: ORGANIZATION_KIND_TO_READABLE_KIND.get(o.kind, o.kind),
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
        "comment": "Organisation habilitée par le Préfet",
        "fn": lambda o: o.is_authorized,
    },
]

TABLE_COLUMNS += get_address_columns(comment_suffix=" de cette organisation")

TABLE_COLUMNS += [
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
    {"name": "longitude", "type": "float", "comment": "Longitude", "fn": lambda o: o.longitude},
    {"name": "latitude", "type": "float", "comment": "Latitude", "fn": lambda o: o.latitude},
]

TABLE_COLUMNS += get_establishment_last_login_date_column()

TABLE_COLUMNS += get_establishment_is_active_column()

TABLE_COLUMNS += [
    {
        "name": "brsa",
        "type": "boolean",
        "comment": "Organisation conventionnée pour le suivi des BRSA",
        "fn": lambda o: o.is_brsa,
    },
]
