"""
Fill the stil non-filled hexa adresses for job seekers that do have either:

- a very high geocoding score (above 0.80)
- an autocompleted address

Any profile that already has a filled hexa address will be left untouched.

It should be run once to backfill all the missing adresses; and then regularly
to update any unfilled hexa address when users autocomplete theirs.

Also, please pay attention to resolve the User geocoding scores BEFORE this.
Why ?
- the BAN API has changed and some low scores might now be higher.
- the before-considered high scores might actually lead to a lot of failures
  since the adress might have changed but not the score (this is very common)
"""

import logging

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User


logger = logging.getLogger(__name__)

MAX_USERS_PER_RUN = 10_000


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )

    def handle(self, wet_run, **options):
        users = User.objects.filter(
            # FIXME(vperron): Someday, also fill users that have an autocompleted address.
            geocoding_score__gte=BAN_API_RELIANCE_SCORE,
            kind=UserKind.JOB_SEEKER,
            is_active=True,
            # no commune is enough to say the address is not filled, as it will fail for the employee records
            jobseeker_profile__hexa_commune=None,
        ).select_related("jobseeker_profile")

        self.stdout.write(f"> count={users.count()} job seekers in need of hexa address resolution.")

        profiles_to_save = []
        for user in users[:MAX_USERS_PER_RUN]:
            try:
                user.jobseeker_profile.update_hexa_address(should_save=False)
                profiles_to_save.append(user.jobseeker_profile)
            except ValidationError:
                self.stdout.write(f"! could not resolve hexa address for {user=}")

        if wet_run:
            JobSeekerProfile.objects.bulk_update(
                profiles_to_save,
                [
                    "hexa_lane_type",
                    "hexa_lane_number",
                    "hexa_std_extension",
                    "hexa_non_std_extension",
                    "hexa_lane_name",
                    "hexa_additional_address",
                    "hexa_post_code",
                    "hexa_commune",
                ],
                batch_size=int(MAX_USERS_PER_RUN / 10),
            )
            self.stdout.write(f"> count={len(profiles_to_save)} hexa addresses resolved.")
