import logging

from django.core.management.base import BaseCommand

from itou.users.models import User


class Command(BaseCommand):
    """
    Deduplicate job seekers.

    To run the command without any change in DB and have a preview of which accounts will be merged:
        django-admin deduplicate_job_seekers --dry-run

    To merge duplicates job seekers in the database:
        django-admin deduplicate_job_seekers
    """

    help = "Deduplicate job seekers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only display data to deduplicate")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity >= 1:
            self.logger.setLevel(logging.DEBUG)

    def merge_easy_cases(self, duplicates, target):
        """
        Merge easy cases: when None or 1 PASS IAE was issued accross multiple accounts.
        """

        assert target.email

        users_to_delete = [u for u in duplicates if u != target]

        self.logger.debug(f"{', '.join([u.email for u in users_to_delete])} => {target.email}")

        for user in users_to_delete:

            assert user.approvals.count() == 0

            if not self.dry_run:
                user.job_applications.update(job_seeker=target)
                user.eligibility_diagnoses.update(job_seeker=target)
                user.delete()

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        self.dry_run = dry_run

        self.logger.debug("Starting. Good luck…")

        count_easy_cases = 0
        count_hard_cases = 0
        hard_cases = []

        duplicates_dict = User.objects.get_duplicates_by_pole_emploi_id(
            prefetch_related_lookups=["approvals", "eligibility_diagnoses"]
        )

        for pe_id, duplicates in duplicates_dict.items():

            users_with_approval = [u for u in duplicates if u.approvals.exists()]

            # Ensure all users have the same birthdate.
            assert all(user.birthdate == duplicates[0].birthdate for user in duplicates)

            # Easy cases.
            # None or 1 PASS IAE was issued for the same person with multiple accounts.
            if len(users_with_approval) <= 1:

                count_easy_cases += 1

                user_with_approval = next((u for u in duplicates if u.approvals.exists()), None)

                # Give priority to the user with a PASS IAE.
                if user_with_approval:
                    self.merge_easy_cases(duplicates, target=user_with_approval)

                # Handle duplicates without any PASS IAE.
                else:

                    # Give priority to the first user who already logged in.
                    first_autonomous_user = next((u for u in duplicates if u.last_login), None)
                    if first_autonomous_user:
                        self.merge_easy_cases(duplicates, target=first_autonomous_user)

                    # Choose an arbitrary user to merge others into.
                    else:
                        self.merge_easy_cases(duplicates, target=duplicates[0])

            # Hard cases.
            # More than one PASS IAE was issued for the same person.
            elif len(users_with_approval) > 1:
                count_hard_cases += 1
                hard_cases.append(duplicates)

        self.logger.debug("-" * 80)
        self.logger.debug(f"{count_easy_cases} easy cases merged.")

        self.logger.debug("-" * 80)
        self.logger.debug(f"{count_hard_cases} hard cases with more than one PASS IAE issued for the same person:")
        self.logger.debug("-" * 80)
        for duplicates in hard_cases:
            self.logger.debug(f"{', '.join([u.email for u in duplicates])}")

        self.logger.debug("-" * 80)
        self.logger.debug("Done.")
