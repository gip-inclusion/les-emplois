from django.contrib.auth import get_user_model
from django.utils import timezone

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.management.commands._utils import get_address_columns, get_first_membership_join_date
from itou.prescribers.models import PrescriberOrganization


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
        return get_user_model().objects.filter(is_prescriber=True, prescribermembership=None).count()
    return org.members.count()


def get_org_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        # Number of job applications made by prescribers without org.
        return JobApplication.objects.filter(
            sender_kind=JobApplication.SENDER_KIND_PRESCRIBER, sender_prescriber_organization=None
        ).count()
    return org.jobapplication_set.count()


def get_org_accepted_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return JobApplication.objects.filter(
            sender_kind=JobApplication.SENDER_KIND_PRESCRIBER,
            sender_prescriber_organization=None,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
        ).count()
    job_applications = list(org.jobapplication_set.all())
    # We have to do all this in python to benefit from prefetch_related.
    return len([ja for ja in job_applications if ja.state == JobApplicationWorkflow.STATE_ACCEPTED])


def get_timedelta_since_org_last_job_application(org):
    if org != ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        job_applications = list(org.jobapplication_set.all())
        # We have to do all this in python to benefit from prefetch_related.
        if len(job_applications) >= 1:
            job_applications.sort(key=lambda o: o.created_at, reverse=True)
            last_job_application = job_applications[0]
            now = timezone.now()
            return now - last_job_application.created_at
    # This field makes no sense for prescribers without org.
    return None


TABLE_COLUMNS = (
    [
        {"name": "id", "type": "integer", "comment": "ID organisation", "lambda": lambda o: o.id},
        {"name": "nom", "type": "varchar", "comment": "Nom organisation", "lambda": lambda o: o.display_name},
        {"name": "type", "type": "varchar", "comment": "Type organisation (PE, ML...)", "lambda": lambda o: o.kind},
        {
            "name": "habilitée",
            "type": "boolean",
            "comment": "Organisation habilitée par le Préfet",
            "lambda": lambda o: o.is_authorized,
        },
    ]
    + get_address_columns(comment_suffix=" de cette organisation")
    + [
        {
            "name": "date_inscription",
            "type": "date",
            "comment": "Date inscription du premier compte prescripteur",
            "lambda": get_org_first_join_date,
        },
        {
            "name": "total_membres",
            "type": "integer",
            "comment": "Nombre de comptes prescripteurs rattachés à cette organisation",
            "lambda": get_org_members_count,
        },
        {
            "name": "total_candidatures",
            "type": "integer",
            "comment": "Nombre de candidatures émises par cette organisation",
            "lambda": get_org_job_applications_count,
        },
        {
            "name": "total_embauches",
            "type": "integer",
            "comment": "Nombre de candidatures en état accepté émises par cette organisation",
            "lambda": get_org_accepted_job_applications_count,
        },
        {
            "name": "temps_écoulé_depuis_dernière_candidature",
            "type": "interval",
            "comment": "Temps écoulé depuis la dernière création de candidature",
            "lambda": get_timedelta_since_org_last_job_application,
        },
    ]
)
