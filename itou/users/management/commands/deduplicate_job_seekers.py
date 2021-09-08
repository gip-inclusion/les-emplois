import logging

from django.core.management.base import BaseCommand

from itou.users.models import User


class Command(BaseCommand):
    """
    Deduplicate job seekers.

    To debug:
        django-admin deduplicate_job_seekers --dry-run

    To populate the database:
        django-admin deduplicate_job_seekers
    """

    help = "Deduplicate job seekers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to import")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        self.stdout.write("Starting. Good luck…")

        count_easy_cases = 0
        count_hard_cases = 0

        for pe_id, duplicates in User.objects.get_duplicated_users_grouped_by_same_pole_emploi_id().items():

            users_with_approval = [u for u in duplicates if u.approvals.exists()]

            same_birthdate = all(user.birthdate == duplicates[0].birthdate for user in duplicates)
            assert same_birthdate

            # Easy cases.
            # None or 1 PASS IAE was issued for the same person with multiple accounts.
            # Keep the user holding the PASS IAE.
            if len(users_with_approval) <= 1:

                count_easy_cases += 1

                user_with_approval = next((u for u in duplicates if u.approvals.exists()), None)

                # Merge duplicates into the one having a PASS IAE.
                if user_with_approval:
                    self.merge(duplicates, into=user_with_approval)

                # Duplicates without PASS IAE.
                else:

                    # Give priority to users who already logged in.
                    first_autonomous_user = next((u for u in duplicates if u.last_login), None)

                    # Merge duplicates into the first autonomous user.
                    if first_autonomous_user:
                        self.merge(duplicates, into=first_autonomous_user)

                    # Choose an arbitrary user to merge others into.
                    else:
                        self.merge(duplicates, into=duplicates[0])

            # Hard cases.
            # More than one PASS IAE was issued for the same person.
            elif len(users_with_approval) > 1:
                count_hard_cases += 1

        self.stdout.write("-" * 80)
        self.stdout.write(f"{count_easy_cases}")  # 6836
        self.stdout.write(f"{count_hard_cases}")  # 375

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")

    def merge(self, duplicates, into):
        print("-" * 80)
        print(into)
        print(duplicates)
