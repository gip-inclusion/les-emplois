from itertools import batched
from math import ceil

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from itou.gps.models import FollowUpGroupMembership
from itou.utils.command import BaseCommand
from itou.www.gps.enums import EndReason


CHUNK_SIZE = 10000


class Command(BaseCommand):
    """
    End old FollowUpMemberships
    """

    help = "End old FollowUpMemberships"

    def handle(self, **options):
        two_years_ago = timezone.now() - relativedelta(years=2)

        old_memberships_pks = list(
            FollowUpGroupMembership.objects.filter(last_contact_at__lte=two_years_ago, ended_at=None)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        self.logger.info(f"Found {len(old_memberships_pks)} old FollowUpGroupMembership to end.")
        chunks_total = ceil(len(old_memberships_pks) / CHUNK_SIZE)

        chunks_count = 0
        for batched_pks in batched(old_memberships_pks, CHUNK_SIZE):
            with transaction.atomic():
                FollowUpGroupMembership.objects.filter(pk__in=batched_pks).update(
                    ended_at=timezone.localdate(), end_reason=EndReason.AUTOMATIC
                )
                chunks_count += 1
                print(f"{chunks_count / chunks_total * 100:.2f}%", end="\r")
