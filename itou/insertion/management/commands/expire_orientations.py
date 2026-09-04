import datetime

from django.db.models import Q
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.utils.command import BaseCommand
from itou.utils.templatetags.str_filters import pluralizefr


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--limit", type=int, default=40)

    @dry_runnable
    def handle(self, *, wet_run, limit, **options):
        now = timezone.now()
        to_expire = (
            Orientation.objects.filter(
                Q(
                    status=OrientationStatus.PENDING,
                    created_at__lte=now - datetime.timedelta(days=Orientation.PENDING_EXPIRATION_PERIOD_DAYS),
                )
                | Q(
                    status=OrientationStatus.PROCESSING,
                    updated_at__lte=now - datetime.timedelta(days=Orientation.PROCESSING_EXPIRATION_PERIOD_DAYS),
                )
            )
            .select_related(
                "beneficiary",
                "sender",
                "sender_prescriber_organization",
                "sender_company",
                "service",
                "service__structure",
            )  # used in the emails
            .order_by("updated_at", "pk")[:limit]
        )

        counter = 0
        for orientation in to_expire:
            orientation.expire()
            counter += 1

        s = pluralizefr(counter)
        self.logger.info(
            f"Found {counter} orientation{s} to expire.",
        )
