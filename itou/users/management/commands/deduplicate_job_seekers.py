import logging

from django.core.management.base import BaseCommand
from django.db.models import Count

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

        # select pole_emploi_id, COUNT(*)
        # from users_user
        # where pole_emploi_id != '' and is_job_seeker is True
        # group by pole_emploi_id
        # having COUNT(*) > 1
        duplicated_pole_emploi_ids = (
            User.objects.values("pole_emploi_id")
            .filter(is_job_seeker=True)
            .exclude(pole_emploi_id="")
            # Skip 31 cases where `00000000` was used as `pole_emploi_id`.
            # We'll probably have to handle them by hand.
            .exclude(pole_emploi_id="00000000")
            .annotate(num_of_duplications=Count("pole_emploi_id"))
            .filter(num_of_duplications__gt=1)
            .values_list("pole_emploi_id", flat=True)
        )

        # Find duplicated `users`.
        users = User.objects.filter(pole_emploi_id__in=duplicated_pole_emploi_ids).prefetch_related("approvals")

        # Group users using the same `pole_emploi_id`:
        # {
        #     '5589555S': [<User: a>, <User: b>],
        #     '7744222A': [<User: x>, <User: y>, <User: z>],
        #     ...
        # }
        users_using_same_pe_id = dict()
        for user in users:
            users_using_same_pe_id.setdefault(user.pole_emploi_id, []).append(user)

        count_easy_cases = 0
        count_hard_cases = 0

        for pe_id, duplicated_users in users_using_same_pe_id.items():

            same_birthdate = all(user.birthdate == duplicated_users[0].birthdate for user in duplicated_users)

            # Users using the same `birthdate`/`pole_emploi_id` are guaranteed to be duplicates.
            if same_birthdate:

                users_with_approval = [u for u in duplicated_users if u.approvals.exists()]

                if len(users_with_approval) <= 1:
                    # None or 1 PASS IAE was issued for the same person with multiple accounts.
                    # Keep the user holding the PASS IAE.
                    count_easy_cases += 1

                elif len(users_with_approval) > 1:
                    # More than one PASS IAE was issued for the same person.
                    count_hard_cases += 1

        self.stdout.write("-" * 80)
        self.stdout.write(f"{count_easy_cases}")  # 6631
        self.stdout.write(f"{count_hard_cases}")  # 374

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
