import logging

from django.core.management.base import BaseCommand

from itou.eligibility import models as eligibility_models
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.prescribers import models as prescribers_models


logger = logging.getLogger(__name__)

HELP_TEXT = """
    Merge a prescriber organization into another. All the data related to the
    first organization will be moved into the second organization. If there is
    no destination organization provided, the first organization will be deleted
    only if it is not attached to any data.
"""


def organization_merge_into(from_id, to_id):
    from_organization = prescribers_models.PrescriberOrganization.objects.get(pk=from_id)
    to_organization = prescribers_models.PrescriberOrganization.objects.get(pk=to_id)
    # Both SIRET and name should be identical
    logger.info(
        "Move organization 'ID %s - SIRET %s - %s' into 'ID %s - SIRET %s - %s'.",
        from_id,
        from_organization.siret,
        from_organization.name,
        to_id,
        to_organization.siret,
        to_organization.name,
    )
    job_applications_models.JobApplication.objects.filter(sender_prescriber_organization_id=from_id).update(
        sender_prescriber_organization_id=to_id
    )
    prescribers_models.PrescriberMembership.objects.filter(organization_id=from_id).update(organization_id=to_id)
    eligibility_models.EligibilityDiagnosis.objects.filter(author_prescriber_organization_id=from_id).update(
        author_prescriber_organization_id=to_id
    )
    invitations_models.PrescriberWithOrgInvitation.objects.filter(organization_id=from_id).update(
        organization_id=to_id
    )
    from_organization.delete()


def organization_delete(from_id):
    from_organization = prescribers_models.PrescriberOrganization.objects.get(pk=from_id)
    logger.info(
        "Delete organization 'ID %s - SIRET %s - %s'.",
        from_id,
        from_organization.siret,
        from_organization.name,
    )
    job_applications_models.JobApplication.objects.filter(sender_prescriber_organization_id=from_id).delete()
    prescribers_models.PrescriberMembership.objects.filter(organization_id=from_id).delete()
    eligibility_models.EligibilityDiagnosis.objects.filter(author_prescriber_organization_id=from_id).delete()
    invitations_models.PrescriberWithOrgInvitation.objects.filter(organization_id=from_id).delete()
    from_organization.delete()


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
            dest="to_if",
            metavar="TO",
            type=int,
            help="ID of the prescriber organization to keep.",
            nargs="?",
            default=None,
        )

    def handle(self, *args, **options):
        if options["to_id"]:
            organization_merge_into(options["from_id"], options["to_id"])
        else:
            organization_delete(options["from_id"])
