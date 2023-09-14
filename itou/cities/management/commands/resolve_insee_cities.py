"""
Fuzzy match an INSEE City to the city name and postcodes of the AddressMixin.

Pretty fast for 1_000 items iterated one by one: 8s.

Very low "miss" rate : 0.51% of the cases (50 000 attempts)

After a run, either:
- objects will have an INSEE city registered
- they will have their geocoding score set to 0 (resolving their city failed)

I think it's fair to agree that for the 0.5% of those pathologic cities
(the name is VERY wrong, or the post code really does not match anything)
that we can ask the users to fix it.
"""

import logging

from django.core.management.base import BaseCommand

from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE, resolve_insee_city
from itou.companies.models import Siae
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    # Keep the running duration low (<10s), no matter the size of the table.
    # After the initial "migration" this command will only take care of the eventual
    # address changes, so probably very few objects at a time.
    BATCH_UPDATE_SIZE = 100
    ITEMS_PER_RUN = 1_000

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )
        parser.add_argument(
            "--mode",
            action="store",
            dest="mode",
            type=str,
            choices=["siaes", "prescribers", "job_seekers"],
            required=True,
        )

    def handle(self, wet_run, mode, **options):
        if mode == "siaes":
            queryset = Siae.objects.active()
            model = Siae
            model_name = "SIAE"
        elif mode == "prescribers":
            queryset = PrescriberOrganization.objects.filter(members__is_active=True)
            model = PrescriberOrganization
            model_name = "PrescriberOrganization"
        elif mode == "job_seekers":
            queryset = User.objects.filter(is_active=True, kind=UserKind.JOB_SEEKER)
            model = User
            model_name = "JobSeeker"

        updated_items = []
        failed_items = []
        qs = (
            queryset.filter(
                geocoding_score__gt=BAN_API_RELIANCE_SCORE,
                insee_city=None,
            )
            .exclude(city="")
            .exclude(post_code="")
            # most recently updated geocoding first, then most recent object.
            .order_by("-geocoding_updated_at", "-pk")
        )
        for item in qs[: self.ITEMS_PER_RUN]:
            if insee_city := resolve_insee_city(item.city, item.post_code):
                item.insee_city = insee_city
                updated_items.append(item)
            else:
                self.stdout.write(f"! failed to find matching city for {item.city=} {item.post_code=}")
                item.geocoding_score = 0  # reset the score to not see them again next run of the cron
                failed_items.append(item)
        if wet_run:
            model.objects.bulk_update(
                updated_items,
                ["insee_city"],
                batch_size=self.BATCH_UPDATE_SIZE,
            )
            model.objects.bulk_update(
                failed_items,
                ["geocoding_score"],
                batch_size=self.BATCH_UPDATE_SIZE,
            )
            self.stdout.write(
                f"> count={len(updated_items)} {model_name} updated. "
                f"err_count={len(failed_items)} {model_name} without a resolution."
            )
