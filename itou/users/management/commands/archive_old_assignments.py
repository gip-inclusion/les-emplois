from itertools import batched

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from itou.users.enums import AssignmentEndReason
from itou.users.models import JobSeekerAssignment
from itou.utils.command import BaseCommand


CHUNK_SIZE = 10_000


class Command(BaseCommand):
    help = "End old FollowUpMemberships"

    # Transaction is handled manually for each batch of objects.
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, **options):
        two_years_ago = timezone.now() - relativedelta(years=2)

        old_assignments_pks = list(
            JobSeekerAssignment.objects.filter(updated_at__lte=two_years_ago, ended_at=None)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        self.logger.info(f"Found {len(old_assignments_pks)} old JobSeekerAsignment to end.")
        for batched_pks in batched(old_assignments_pks, CHUNK_SIZE):
            with transaction.atomic():
                JobSeekerAssignment.objects.filter(pk__in=batched_pks).update(
                    ended_at=timezone.now(), end_reason=AssignmentEndReason.AUTOMATIC
                )
