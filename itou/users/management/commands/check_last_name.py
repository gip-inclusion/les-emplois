from django.db.models import F
from itoutils.django.commands import dry_runnable

from itou.users.enums import UserKind
from itou.users.models import User
from itou.users.utils import GuessLastNameMode, guess_last_name
from itou.utils.command import BaseCommand


# FIXME (dbaty, 2026-11-18): remove around mid-december 2027, once
# we're sure we have no bug in our "populate last_name" process.
class Command(BaseCommand):
    ATOMIC_HANDLE = True
    help = "Report (and possibly fix with `--fix --wet-run`) inconsistencies between last name and birth name"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")
        parser.add_argument("--fix", action="store_true", dest="fix")

    @dry_runnable
    def handle(self, *, wet_run, fix, **options):
        # Python code uses `casefold()` but our PostgreSQL 17 does not
        # have the corresponding function (it appeared in version
        # 18). Instead, use `lower()` in SQL, and then `casefold()` in
        # Python below.
        users = (
            User.objects.filter(kind=UserKind.JOB_SEEKER)
            .exclude(last_name="", jobseeker_profile__birth_name="")
            .exclude(last_name=F("jobseeker_profile__birth_name"))
        ).select_related("jobseeker_profile")
        inconsistencies = []
        for user in users:
            birth_name = user.jobseeker_profile.birth_name
            last_name = guess_last_name(user.last_name, birth_name, GuessLastNameMode.BEFORE_SAVE)
            if user.last_name != last_name:
                user.last_name_to_fix = last_name
                inconsistencies.append(user)
        self.logger.info(
            "Found %d last name / birth name inconsistencies: %s",
            len(inconsistencies),
            [user.pk for user in inconsistencies],
        )

        if fix:
            updates = []
            for user in inconsistencies:
                user.last_name = user.last_name_to_fix
                updates.append(user)
            User.objects.bulk_update(updates, ["last_name"])
            self.logger.info("Updated inconsistent last name of %d users", len(inconsistencies))
