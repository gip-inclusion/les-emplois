import django.db.transaction as transaction
import xworkflows
from django.utils import timezone

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """Performs checks and fixes on known employee records glitches."""

    # Limit to 10 as we shouldn't have more than that in nominal situations, but mainly because we are
    # limited by how much we can transfer: 1 file, 700 rows, every 2 hours on weekdays.
    # The command is executed every hour, so on Monday morning we will have more than 600 rows to send.
    MAX_MISSED_NOTIFICATIONS_CREATED = 10

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Just check and report, don't fix anything",
        )

    # Check and fix methods: add as many as needed.

    def _check_approvals(self, dry_run):
        # Report employee records with no approvals
        # (approvals can be deleted after processing)

        no_approval = EmployeeRecord.objects.select_related("job_application").filter(
            job_application__approval__isnull=True
        )
        count_no_approval = no_approval.count()

        self.logger.info("found %d employee records with missing approval", count_no_approval)
        if count_no_approval:
            if dry_run:
                return

            delete_nb, _delete_info = no_approval.delete()
            self.logger.info("deleted %d/%d employee records with missing approval", delete_nb, count_no_approval)

    @transaction.atomic()
    def _check_missed_notifications(self, dry_run):
        self.stdout.write("* Checking missing employee records notifications:")
        employee_record_with_missing_notification = (
            EmployeeRecord.objects.missed_notifications()
            .filter(
                status=Status.ARCHIVED,
                job_application__approval__end_at__gte=timezone.now(),  # Take approvals that can still be used
            )
            .order_by(
                "-job_application__approval__updated_at",
                "job_application__approval__number",
                "job_application__to_company__siret",
            )
        )

        self.logger.info(
            "found %d missed employee records notifications", len(employee_record_with_missing_notification)
        )

        unarchive_count = 0
        if not dry_run:
            for employee_record in employee_record_with_missing_notification[: self.MAX_MISSED_NOTIFICATIONS_CREATED]:
                try:
                    employee_record.unarchive()
                except xworkflows.AbortTransition:
                    self.logger.exception("Failed to unarchive employee_record=%s", employee_record)
                else:
                    unarchive_count += 1
        self.logger.info(
            "%d/%d employee records were unarchived", unarchive_count, len(employee_record_with_missing_notification)
        )

    def handle(self, *, dry_run, **options):
        self.logger.info("Checking employee records coherence before transferring to ASP")

        if dry_run:
            self.logger.info("DRY-RUN mode: not fixing, just reporting")

        self._check_approvals(dry_run)
        self._check_missed_notifications(dry_run)

        self.logger.info("Employee records sanitizing done. Have a great day!")
