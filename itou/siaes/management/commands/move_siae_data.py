import argparse
import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.eligibility import models as eligibility_models
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.siaes import models as siaes_models
from itou.users import models as users_models


logger = logging.getLogger(__name__)

HELP_TEXT = """
    Move all data from siae A to siae B (or only the job applications if `only-job-applications` option is set).
    After this move siae A is no longer supposed to be used or even accessible.
    Members of siae A are detached, geolocalization is removed and new job applications are blocked.

    This command should be used when users have been using the wrong siae A instead of using the correct siae B.

    Siae A is *not* deleted at the end. This is because it might not always be possible or make sense to do so
    and because cleaning up irrelevant siaes is actually the job of the import_siae command.

    You will most likely still have manual actions to do after the move, typically deactivating the convention
    of siae A. That one cannot be automated because it has drastic consequences as it disables all siaes of the
    same convention. So be sure to read your trello ticket instructions thoroughly and don't assume this command
    does everything.

    Examples of use in local dev:
    $ make django_admin COMMAND="move_siae_data --from 3243 --to 9612 --dry-run"
    $ make django_admin COMMAND="move_siae_data --from 3243 --to 9612 --only-job-applications --dry-run"

    And in production:
    $ cd && cd app_* && django-admin move_siae_data --from 3243 --to 9612 --dry-run

"""


def move_siae_data(from_id, to_id, dry_run=False, only_job_applications=False):
    if from_id == to_id:
        logger.error("Unable to use the same siae as source and destination (ID %s)", from_id)
        return

    from_siae_qs = siaes_models.Siae.objects.filter(pk=from_id)
    try:
        from_siae = from_siae_qs.get()
    except siaes_models.Siae.DoesNotExist:
        logger.error("Unable to find the siae ID %s", from_id)
        return

    to_siae_qs = siaes_models.Siae.objects.filter(pk=to_id)
    try:
        to_siae = to_siae_qs.get()
    except siaes_models.Siae.DoesNotExist:
        logger.error("Unable to find the siae ID %s", to_id)
        return

    if from_siae.kind != to_siae.kind:
        logger.error("Both siaes should have the same kind but they don't")
        return

    # Intermediate variable for better readability
    move_all_data = not only_job_applications

    logger.info(
        "MOVE %s OF siae.id=%s - %s %s - %s",
        "DATA" if move_all_data else "JOB APPLICATIONS",
        from_siae.pk,
        from_siae.kind,
        from_siae.siret,
        from_siae.display_name,
    )

    job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=from_id)
    logger.info("| Job applications sent: %s", job_applications_sent.count())

    job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=from_id)
    logger.info("| Job applications received: %s", job_applications_received.count())

    if move_all_data:
        job_descriptions = siaes_models.SiaeJobDescription.objects.filter(siae_id=from_id)
        logger.info("| Job descriptions: %s", job_descriptions.count())

        # Move users not already present in siae destination
        members = siaes_models.SiaeMembership.objects.filter(siae_id=from_id).exclude(
            user__in=users_models.User.objects.filter(siaemembership__siae_id=to_id)
        )
        logger.info("| Members: %s", members.count())

        diagnoses = eligibility_models.EligibilityDiagnosis.objects.filter(author_siae_id=from_id)
        logger.info("| Diagnoses: %s", diagnoses.count())

        prolongations = approvals_models.Prolongation.objects.filter(declared_by_siae_id=from_id)
        logger.info("| Prolongations: %s", prolongations.count())

        suspensions = approvals_models.Suspension.objects.filter(siae_id=from_id)
        logger.info("| Suspensions: %s", suspensions.count())

        # Don't move invitations for existing members
        # The goal is to keep information about the original information
        invitations = invitations_models.SiaeStaffInvitation.objects.filter(siae_id=from_id).exclude(
            email__in=users_models.User.objects.filter(siaemembership__siae_id=to_id).values_list("email", flat=True)
        )
        logger.info("| Invitations: %s", invitations.count())

    logger.info(
        "INTO siae.id=%s - %s %s - %s",
        to_siae.pk,
        to_siae.kind,
        to_siae.siret,
        to_siae.display_name,
    )

    dest_siae_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=to_id)
    logger.info("| Job applications sent: %s", dest_siae_job_applications_sent.count())

    dest_siae_job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=to_id)
    logger.info("| Job applications received: %s", dest_siae_job_applications_received.count())

    if dry_run:
        logger.info("Nothing to do in dry run mode.")
        return

    with transaction.atomic():

        # If we move the job applications without moving the job descriptions as well, we need to unlink them,
        # as job applications will be attached to siae B but job descriptions will stay attached to siae A.
        if only_job_applications:
            for job_application in job_applications_sent:
                job_application.selected_jobs.clear()
            for job_application in job_applications_received:
                job_application.selected_jobs.clear()

        job_applications_sent.update(sender_siae_id=to_id)
        job_applications_received.update(to_siae_id=to_id)

        if move_all_data:
            job_descriptions.update(siae_id=to_id)
            members.update(siae_id=to_id)
            diagnoses.update(author_siae_id=to_id)
            prolongations.update(declared_by_siae_id=to_id)
            suspensions.update(siae_id=to_id)
            invitations.update(siae_id=to_id)
            to_siae_qs.update(
                brand=from_siae.display_name,
                description=from_siae.description,
                phone=from_siae.phone,
                coords=from_siae.coords,
                geocoding_score=from_siae.geocoding_score,
            )
            from_siae_qs.update(
                block_job_applications=True,
                job_applications_blocked_at=timezone.now(),
                # Make sure the old siae no longer appears in results
                coords=None,
                geocoding_score=None,
            )

    logger.info("MOVE %s OF siae.id=%s FINISHED", "DATA" if move_all_data else "JOB APPLICATIONS", from_siae.pk)
    orig_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=from_id)
    logger.info("| Job applications sent: %s", orig_job_applications_sent.count())

    orig_job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=from_id)
    logger.info("| Job applications received: %s", orig_job_applications_received.count())

    logger.info("INTO siae.id=%s", to_siae.pk)

    dest_siae_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=to_id)
    logger.info("| Job applications sent: %s", dest_siae_job_applications_sent.count())

    dest_siae_job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=to_id)
    logger.info("| Job applications received: %s", dest_siae_job_applications_received.count())


class Command(BaseCommand):
    help = HELP_TEXT

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_id",
            metavar="FROM",
            type=int,
            help="ID of the siae to move data from.",
            required=True,
        )
        parser.add_argument(
            "--to",
            dest="to_id",
            metavar="TO",
            type=int,
            help="ID of the the siae to move data to.",
            required=True,
        )
        parser.add_argument(
            "--only-job-applications",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Set to True to move only job applications, nothing else!",
        )
        parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)

    def handle(self, *args, **options):
        move_siae_data(options["from_id"], options["to_id"], options["dry_run"], options["only_job_applications"])
