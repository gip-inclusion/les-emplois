"""
Useful command to match an INSEE City to the city name and postcodes of the AddressMixin.

Pretty fast for 1_000 items iterated one by one: 8s.

Very low "miss" rate : 0.51% of the cases (50 000 attempts)
"""

import logging

from django.core.management.base import BaseCommand

from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE, resolve_insee_city


logger = logging.getLogger(__name__)

ITEMS_PER_RUN = 1_000


class BaseInseeCityResolverCommand(BaseCommand):
    queryset = None

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )

    @property
    def model(self):
        return self.queryset.model

    @property
    def model_name(self):
        return self.model.__name__

    def handle(self, wet_run, **options):
        updated_items = []
        failed_items = []
        qs = (
            self.queryset.filter(
                geocoding_score__gt=BAN_API_RELIANCE_SCORE,
                insee_city=None,
            )
            .exclude(city="")
            .exclude(post_code="")
            # most recently updated geocoding first then most recent.
            .order_by("-geocoding_updated_at", "-pk")
        )
        for item in qs[:ITEMS_PER_RUN]:
            if insee_city := resolve_insee_city(item.city, item.post_code):
                item.insee_city = insee_city
                updated_items.append(item)
            else:
                self.stdout.write(f"! failed to find matching city for {item.city=} {item.post_code=}")
                item.geocoding_score = 0  # reset the score to not see them again next run of the cron
                failed_items.append(item)
        if wet_run:
            self.model.objects.bulk_update(
                updated_items,
                ["insee_city"],
                batch_size=100,
            )
            self.model.objects.bulk_update(
                failed_items,
                ["geocoding_score"],
                batch_size=100,
            )
            self.stdout.write(
                f"> count={len(updated_items)} {self.model_name} updated. "
                f"err_count={len(failed_items)} {self.model_name} without a resolution."
            )
