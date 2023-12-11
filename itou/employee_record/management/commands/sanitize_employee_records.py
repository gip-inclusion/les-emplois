import django.db.transaction as transaction
from django.db.models import F, Max
from django.db.models.functions import Greatest
from django.utils import timezone

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """Performs checks and fixes on known employee records glitches."""

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Just check and report, don't fix anything",
        )

    # Check and fix methods: add as many as needed.

    def _check_3436_error_code(self, dry_run):
        # Report all employee records with ASP error code 3436

        err_3436 = EmployeeRecord.objects.asp_duplicates()
        count_3436 = err_3436.count()

        self.stdout.write("* Checking REJECTED employee records with error 3436 (duplicates):")

        if count_3436 == 0:
            self.stdout.write(" - none found (great!)")
        else:
            self.stdout.write(f" - found {count_3436} error(s)")

            if dry_run:
                return

            self.stdout.write(" - fixing 3436 errors: forcing status to PROCESSED")

            with transaction.atomic():
                for to_fix in err_3436:
                    to_fix.update_as_processed_as_duplicate(to_fix.archived_json)

            self.stdout.write(" - done!")

    def _check_jobseeker_profiles(self, dry_run):
        # Check incoherence in user profile leading to validation errors at processing time.
        # Employee records in this case are switched back to status DISABLED for further processing by end-user.
        # Most frequent error cases are:
        # - no HEXA address

        profile_selected = EmployeeRecord.objects.filter(status=Status.PROCESSED).select_related(
            "job_application",
            "job_application__job_seeker__jobseeker_profile",
            "job_application__job_seeker__jobseeker_profile__hexa_commune",
        )
        no_hexa_address = profile_selected.filter(
            job_application__job_seeker__jobseeker_profile__hexa_commune__isnull=True
        )
        count_no_hexa_address = no_hexa_address.count()

        self.stdout.write("* Checking employee records job seeker profile:")

        if count_no_hexa_address == 0:
            self.stdout.write(" - no profile found with invalid HEXA address (great!)")
        else:
            self.stdout.write(f" - found {count_no_hexa_address} job seeker profile(s) without HEXA address")

            if dry_run:
                return

            self.stdout.write(" - fixing missing address in profiles: switching status to DISABLED")

            with transaction.atomic():
                for without_address in no_hexa_address:
                    without_address.update_as_disabled()

            self.stdout.write(" - done!")

    def _check_approvals(self, dry_run):
        # Report employee records with no approvals
        # (approvals can be deleted after processing)

        no_approval = EmployeeRecord.objects.select_related("job_application").filter(
            job_application__approval__isnull=True
        )
        count_no_approval = no_approval.count()

        self.stdout.write("* Checking missing employee records approval:")

        if count_no_approval == 0:
            self.stdout.write(" - no missing approval (great!)")
        else:
            self.stdout.write(f" - found {count_no_approval} missing approval(s)")

            if dry_run:
                return

            self.stdout.write(" - fixing missing approvals: DELETING employee records")

            no_approval.delete()

            self.stdout.write(" - done!")

    @transaction.atomic()
    def _check_missed_notifications(self, dry_run):
        self.stdout.write("* Checking missing employee records notifications:")
        prolongation_cutoff = timezone.now()
        employee_record_with_missing_notification = (
            EmployeeRecord.objects.annotate(
                last_employee_record_snapshot=Greatest(
                    # We take `updated_at` and not `created_at` to mimic how the trigger would have behaved if the
                    # employee record was never ARCHIVED. For exemple, if the ER was DISABLED before ARCHIVED then no
                    # notification would have been sent, the trigger ask for a PROCESSED, if a prolongation was
                    # submitted between those two events.
                    F("updated_at"),
                    Max(F("update_notifications__created_at")),
                ),
                last_approval_change=Greatest(
                    F("job_application__approval__created_at"),
                    # We only use prolongations because even if a suspension will postpone the approval's end date
                    # it's not really useful to the employee on the ASP side, and it significantly speeds up the query.
                    Max(F("job_application__approval__prolongation__created_at")),
                ),
            )
            .filter(
                status=Status.ARCHIVED,
                job_application__approval__end_at__gte=prolongation_cutoff,  # Take approvals that can still be used
                last_employee_record_snapshot__lt=F("last_approval_change"),
            )
            .order_by(
                "job_application__approval__number",
                "job_application__to_company__siret",
            )
        )

        self.stdout.write(f" - found {len(employee_record_with_missing_notification)} missing notification(s)")

        total_created = 0
        if not dry_run:
            for employee_record in employee_record_with_missing_notification:
                _, created = EmployeeRecordUpdateNotification.objects.update_or_create(
                    employee_record=employee_record,
                    status=Status.NEW,
                    defaults={"updated_at": timezone.now},
                )
                total_created += int(created)
            self.stdout.write(f" - {total_created} notification(s) created")
        self.stdout.write(" - done!")

    def handle(self, *, dry_run, **options):
        self.stdout.write("+ Checking employee records coherence before transferring to ASP")

        if dry_run:
            self.stdout.write(" - DRY-RUN mode: not fixing, just reporting")

        self._check_approvals(dry_run)
        self._check_jobseeker_profiles(dry_run)
        self._check_3436_error_code(dry_run)
        self._check_missed_notifications(dry_run)

        self.stdout.write("+ Employee records sanitizing done. Have a great day!")
