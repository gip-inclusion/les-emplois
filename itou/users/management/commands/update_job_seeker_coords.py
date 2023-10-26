"""
This script is intended to regularly try and update our job seeker's geolocation.

It is essential to give us useful, quantitative insight about those.

At the time of writing, it seems that a "good" score is "anything above 0.68", more or less.

By looking at the results file manually, it seems that there are very few (less than 5%)
false positives, meaning a resolved address that does not look like the submitted one.

Then, to get some quantitative results, out of 42 000 job seekers without coordinates:

- 56% are now geolocated with a score above 0.80 (almost zero false positives then)
- 66% are now geolocated with a score above 0.68.
- 10% only (~4000 users) are still not geolocated at all.

We could agree on running this script regularly to keep any result above 0.80 and thus
get the best possible geolocation for our users.

"""

import logging

from itou.common_apps.address.models import geolocate_qs
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )

    def handle(self, wet_run, **options):
        users = User.objects.filter(kind=UserKind.JOB_SEEKER, is_active=True)

        users_to_save = list(geolocate_qs(users, is_verbose=True))
        if wet_run:
            User.objects.bulk_update(
                users_to_save,
                ["coords", "geocoding_score", "ban_api_resolved_address", "geocoding_updated_at"],
                batch_size=1000,
            )
            self.stdout.write(f"> count={len(users_to_save)} job seekers geolocated with a high score.")
