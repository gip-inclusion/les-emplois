import datetime
import logging

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.emails import JobSeekerEmailFactory
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.emails import send_email_messages


logger = logging.getLogger(__name__)


INACTIVITY_DURATION = relativedelta(months=13)
GRACE_PERIOD = datetime.timedelta(days=30)


class DummyRollback(Exception):
    """Exception to catch on rollback"""


class Command(BaseCommand):
    BATCH_SIZE = 100

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Send upcoming deletion emails to inactive job seekers",
        )

    @monitor(monitor_slug="notify-upcoming-deletion-for-jobseekers")
    def handle(self, *args, wet_run, **options):
        try:
            with transaction.atomic():
                self._handle(wet_run)
                if not wet_run:
                    raise DummyRollback()
        except DummyRollback:
            self.logger.info("DRY RUN - Transaction rollbacked")

    def _handle(self, wet_run):
        dry_run_prefix = "DRY RUN -" if not wet_run else ""
        last_activity_threshold = timezone.now() - INACTIVITY_DURATION
        job_seekers_with_last_activity = User.objects.job_seekers_with_last_activity()

        # Reset notification if there has been activity since the notification
        nb_updated = job_seekers_with_last_activity.filter(
            upcoming_deletion_notified_at__lt=F("last_activity")
        ).update(upcoming_deletion_notified_at=None)
        self.logger.info("%s Upcoming deletion cancelled for %s job seekers", dry_run_prefix, nb_updated)

        # Single out deletable job seekers (i.e. without any accepted application)
        deletable_job_seekers = job_seekers_with_last_activity.exclude(
            # that have no accepted job application & no approval
            Exists(
                JobApplication.objects.filter(
                    job_seeker_id=OuterRef("pk"),
                    state=JobApplicationWorkflow.STATE_ACCEPTED,
                )
            )
            | Exists(
                Approval.objects.filter(
                    user_id=OuterRef("pk"),
                )
            )
        )

        # Notify deletable job seekers without recent activity
        job_seekers_to_notify = deletable_job_seekers.filter(
            upcoming_deletion_notified_at__isnull=True,
            last_activity__lt=last_activity_threshold,
        ).order_by("-last_activity")
        self.logger.info("%s Found %s inactive job seekers to notify", dry_run_prefix, job_seekers_to_notify.count())
        upcoming_deletion_emails = []
        notified_users = []
        upcoming_deletion_date = timezone.now() + GRACE_PERIOD
        for job_seeker in job_seekers_to_notify[: self.BATCH_SIZE]:
            upcoming_deletion_emails.append(
                JobSeekerEmailFactory(job_seeker).info_about_upcoming_deletion(upcoming_deletion_date)
            )
            notified_users.append(job_seeker.pk)
        User.objects.filter(pk__in=notified_users).update(upcoming_deletion_notified_at=timezone.now())
        self.logger.info("%s Updated %s inactive job seekers as notified", dry_run_prefix, len(notified_users))

        # Delete inactive job seeker that were already notified
        job_seekers_to_delete = deletable_job_seekers.filter(
            upcoming_deletion_notified_at__lt=timezone.now() - GRACE_PERIOD,
            last_activity__lt=F("upcoming_deletion_notified_at"),
        )
        self.logger.info("%s Found %s inactive job seekers to delete", dry_run_prefix, job_seekers_to_delete.count())
        deletion_emails = []
        deleted_users = []
        for job_seeker in job_seekers_to_delete[: self.BATCH_SIZE]:
            deletion_emails.append(JobSeekerEmailFactory(job_seeker).deletion_completed())
            deleted_users.append(job_seeker.pk)
        deleted_objects = User.objects.filter(pk__in=deleted_users).delete()
        self.logger.info("%s Deleted %s inactive job seekers: %s", dry_run_prefix, len(deleted_users), deleted_objects)

        if wet_run:
            send_email_messages(upcoming_deletion_emails + deletion_emails)
        self.logger.info("%s %s emails sent for upcoming deletion", dry_run_prefix, len(upcoming_deletion_emails))
        self.logger.info("%s %s emails sent for confirmed deletion", dry_run_prefix, len(deletion_emails))
