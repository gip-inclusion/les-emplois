import argparse
import logging

from django.db import transaction

from itou.approvals import models as approvals_models
from itou.eligibility import models as eligibility_models
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.prescribers import models as prescribers_models
from itou.users import models as users_models
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

HELP_TEXT = """
    Merge a prescriber organization into another. All the data related to the
    first organization will be moved into the second organization. If there is
    no destination organization provided, the first organization will be deleted
    only if it is not attached to any data.
"""


def _model_sanity_check():
    # Sanity check to prevent dangerous deletes
    relation_fields = {
        field.name
        for field in prescribers_models.PrescriberOrganization._meta.get_fields()
        if field.is_relation and not field.many_to_one
    }
    expected_fields = {
        "eligibilitydiagnosis",
        "geiqeligibilitydiagnosis",
        "invitations",
        "jobapplication",
        "members",
        "prescribermembership",
        "prolongation",
        "prolongationrequest",
        "notification_settings",
    }
    if relation_fields != expected_fields:
        raise RuntimeError(
            f"Extra relations found, please update this script to handle: {relation_fields ^ expected_fields}"
        )


def organization_merge_into(from_id, to_id, *, wet_run):
    _model_sanity_check()

    if from_id == to_id:
        logger.error("Unable to use the same organization as source and destination (ID %s)", from_id)
        return

    try:
        from_organization = prescribers_models.PrescriberOrganization.objects.get(pk=from_id)
    except prescribers_models.PrescriberOrganization.DoesNotExist:
        logger.error("Unable to find the organization ID %s", from_id)
        return

    try:
        to_organization = prescribers_models.PrescriberOrganization.objects.get(pk=to_id)
    except prescribers_models.PrescriberOrganization.DoesNotExist:
        logger.error("Unable to find the organization ID %s", to_id)
        return

    # Both SIRET and name should be identical
    logger.info(
        "MERGE organization 'ID %s - SIRET %s - %s'",
        from_id,
        from_organization.siret,
        from_organization.name,
    )

    job_applications = job_applications_models.JobApplication.objects.filter(sender_prescriber_organization_id=from_id)
    logger.info("| Job applications: %s", job_applications.count())

    # Move users not already present in organization destination
    members = prescribers_models.PrescriberMembership.objects.filter(organization_id=from_id).exclude(
        user__in=users_models.User.objects.filter(prescribermembership__organization_id=to_id)
    )
    logger.info("| Members: %s", members.count())

    diagnoses = eligibility_models.EligibilityDiagnosis.objects.filter(author_prescriber_organization_id=from_id)
    logger.info("| Diagnoses: %s", diagnoses.count())

    geiq_diagnoses = eligibility_models.GEIQEligibilityDiagnosis.objects.filter(
        author_prescriber_organization_id=from_id
    )
    logger.info("| GEIQ Diagnoses: %s", geiq_diagnoses.count())

    # Don't move invitations for existing members
    # The goal is to keep information about the original information
    invitations = invitations_models.PrescriberWithOrgInvitation.objects.filter(organization_id=from_id).exclude(
        email__in=users_models.User.objects.filter(prescribermembership__organization_id=to_id).values_list(
            "email", flat=True
        )
    )
    logger.info("| Invitations: %s", invitations.count())

    logger.info(
        "INTO organization 'ID %s - SIRET %s - %s'",
        to_id,
        to_organization.siret,
        to_organization.name,
    )

    # Prolongations have links (fks) on a prescriber and a prescriber organization
    # for validation concerns on some specific prolongation reasons
    prolongations = approvals_models.Prolongation.objects.filter(prescriber_organization_id=from_id)
    logger.info("| Prolongations: %s", prolongations.count())
    prolongation_requests = approvals_models.ProlongationRequest.objects.filter(prescriber_organization_id=from_id)
    logger.info("| Prolongation Requests: %s", prolongation_requests.count())

    if wet_run:
        with transaction.atomic():
            job_applications.update(sender_prescriber_organization_id=to_id)
            members.update(organization_id=to_id)
            diagnoses.update(author_prescriber_organization_id=to_id)
            geiq_diagnoses.update(author_prescriber_organization_id=to_id)
            invitations.update(organization_id=to_id)
            prolongations.update(prescriber_organization_id=to_id)
            prolongation_requests.update(prescriber_organization_id=to_id)
            from_organization.delete()
    else:
        logger.info("Nothing to do in dry run mode.")


class Command(BaseCommand):
    help = HELP_TEXT

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_id",
            metavar="FROM",
            type=int,
            help="ID of the prescriber organization to delete.",
            required=True,
        )
        parser.add_argument(
            "--to",
            dest="to_id",
            metavar="TO",
            type=int,
            help="ID of the prescriber organization to keep.",
            required=True,
        )
        parser.add_argument("--wet-run", action=argparse.BooleanOptionalAction, default=False)

    def handle(self, from_id, to_id, *, wet_run, **options):
        organization_merge_into(from_id, to_id, wet_run=wet_run)
