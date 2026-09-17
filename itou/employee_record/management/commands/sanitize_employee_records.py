import re

import xworkflows
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.users.models import JobSeekerProfile
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """Performs checks and fixes on known employee records glitches."""

    ATOMIC_HANDLE = True

    # Limit to 10 as we shouldn't have more than that in nominal situations, but mainly because we are
    # limited by how much we can transfer: 1 file, 700 rows, every 2 hours on weekdays.
    # The command is executed every hour, so on Monday morning we will have more than 600 rows to send.
    MAX_MISSED_NOTIFICATIONS_CREATED = 10

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    # Check and fix methods: add as many as needed.

    def _check_approvals(self):
        # Report employee records with no approvals
        # (approvals can be deleted after processing)

        no_approval = EmployeeRecord.objects.select_related("job_application").filter(
            job_application__approval__isnull=True
        )
        count_no_approval = no_approval.count()

        self.logger.info("found %d employee records with missing approval", count_no_approval)
        if count_no_approval:
            delete_nb, _delete_info = no_approval.delete()
            self.logger.info("deleted %d/%d employee records with missing approval", delete_nb, count_no_approval)

    def _check_missed_notifications(self):
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

    def _handle_3437_errors(self):
        # Rejected records with the asp_processing_code 3437
        # The ASP now returns the "expected" asp_uid that can be handled automatically.
        # XXX: this processing will be moved to batch file processing in a second time.
        for employee_record in (
            EmployeeRecord.objects.filter(
                status=Status.REJECTED,
                asp_processing_code=EmployeeRecord.ASP_UNIQUE_ID_MISMATCH_CODE,
            )
            .select_related("job_application__job_seeker__jobseeker_profile")
            .order_by(
                "created_at",
            )
        ):
            # The label looks like: "Un salarié existe déjà pour cette structure avec un identifiant Plate-forme
            # de l'inclusion différent. (ASP_UID)"
            match = re.search(r"\(([^)]+)\)", employee_record.asp_processing_label)
            if match is None:
                self.logger.error(
                    "Could not extract asp_uid from asp_processing_label of employee_record=%s", employee_record.pk
                )
                continue

            asp_uid = match.group(1)
            if not re.match(r"^[0-9a-f]{30}$", asp_uid):
                self.logger.error(
                    "Could not extract asp_uid from asp_processing_label of employee_record=%s", employee_record.pk
                )
                continue
            if jobseeker_profile := JobSeekerProfile.objects.filter(asp_uid=asp_uid).first():
                # We have a duplicate job seeker to handle manually
                self.logger.info(
                    "employee_record=%s is likely linked to job_seeker=%s",
                    employee_record.pk,
                    jobseeker_profile.user_id,
                )
                continue
            employee_record.job_application.job_seeker.jobseeker_profile.asp_uid = asp_uid
            employee_record.job_application.job_seeker.jobseeker_profile.save(update_fields={"asp_uid"})
            self.logger.info(
                "Updated asp_uid field of job_seeker=%s according to ASP response for employee_record=%s",
                employee_record.job_application.job_seeker_id,
                employee_record.pk,
            )
            try:
                employee_record.ready()
            except Exception as exc:
                self.logger.warning(
                    "Could not automatically make employee_record=%s ready - exc=%s", employee_record.pk, exc
                )

    @dry_runnable
    def handle(self, **options):
        self.logger.info("Checking employee records coherence before transferring to ASP")

        self._check_approvals()
        self._check_missed_notifications()
        self._handle_3437_errors()

        self.logger.info("Employee records sanitizing done. Have a great day!")
