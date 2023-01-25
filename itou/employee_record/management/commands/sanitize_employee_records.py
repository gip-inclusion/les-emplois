import django.db.transaction as transaction
from django.core.management.base import BaseCommand

from itou.employee_record.models import EmployeeRecord


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

    # Check and fix methods: add as many as needed..

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

    def _check_orphans(self, dry_run):
        # Report all orphans employee records (bad asp_id)

        orphans = EmployeeRecord.objects.orphans()

        self.stdout.write("* Checking orphans employee records:")

        if len(orphans) == 0:
            self.stdout.write(" - none found (great!)")
        else:
            self.stdout.write(f" - found {len(orphans)} orphan(s)")

            if dry_run:
                return

            self.stdout.write(" - fixing orphans: switching status to DISABLED")

            with transaction.atomic():
                for orphan in orphans:
                    if orphan.can_be_disabled:
                        orphan.update_as_disabled()

            self.stdout.write(" - done!")

    def _check_jobseeker_profiles(self, dry_run):
        # Check incoherences in user profile leading to validation errors at processing time.
        # Employee records in this case are switched back to status NEW for further processing by end-user.
        # Most frequent error cases are:
        # - no HEXA address
        # - no profile at all (?)

        profile_selected = EmployeeRecord.objects.filter(
            status__in=EmployeeRecord.CAN_BE_DISABLED_STATES
        ).select_related(
            "job_application",
            "job_application__job_seeker__jobseeker_profile",
            "job_application__job_seeker__jobseeker_profile__hexa_commune",
        )
        no_hexa_address = profile_selected.filter(
            job_application__job_seeker__jobseeker_profile__hexa_commune__isnull=True
        )
        count_no_hexa_address = no_hexa_address.count()
        no_job_seeker_profile = profile_selected.filter(job_application__job_seeker__jobseeker_profile__isnull=True)
        count_no_job_seeker_profile = no_job_seeker_profile.count()

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

        if count_no_job_seeker_profile == 0:
            self.stdout.write(" - no empty job seeker profile found (great!)")
        else:
            self.stdout.write(f" - found {count_no_job_seeker_profile} empty job seeker profile(s)")

            if dry_run:
                return

            self.stdout.write(" - fixing missing jobseeker profiles: switching status to DISABLED")

            with transaction.atomic():
                for without_profile in no_job_seeker_profile:
                    without_profile.update_as_disabled()

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

    def handle(self, dry_run=False, **options):
        self.stdout.write("+ Checking employee records coherence before transfering to ASP")

        if dry_run:
            self.stdout.write(" - DRY-RUN mode: not fixing, just reporting")

        self._check_approvals(dry_run)
        self._check_jobseeker_profiles(dry_run)
        self._check_3436_error_code(dry_run)
        self._check_orphans(dry_run)

        self.stdout.write("+ Employee records sanitizing done. Have a great day!")
