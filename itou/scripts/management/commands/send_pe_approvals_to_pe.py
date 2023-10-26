from time import sleep

from django.db.models import Q
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.utils.apis import enums as api_enums
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Regularly sends all 'pending' and 'should retry' PE approvals to PE"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--delay", action="store", dest="delay", default=0, type=int, choices=range(0, 5))

    def handle(self, *, wet_run, delay, **options):
        now = timezone.now()

        # change all the PoleEmploiApproval state to "error" if we can't get information on it.
        # we never update the Pole Emploi Approvals, so it will never be fixed.
        approvals_models.PoleEmploiApproval.objects.filter(
            Q(nir="") | Q(nir=None) | Q(first_name="") | Q(last_name="") | Q(siae_siret=None) | Q(siae_kind=None)
        ).update(
            pe_notification_status=api_enums.PEApiNotificationStatus.ERROR,
            pe_notification_time=now,
            pe_notification_exit_code=api_enums.PEApiPreliminaryCheckFailureReason.MISSING_USER_DATA,
        )

        # Now select all the others and let's get started.
        queryset = approvals_models.PoleEmploiApproval.objects.filter(
            pe_notification_status__in=[
                api_enums.PEApiNotificationStatus.PENDING,
                api_enums.PEApiNotificationStatus.SHOULD_RETRY,
            ],
        ).order_by("-start_at")

        self.stdout.write(f"PE approvals needing to be sent count={queryset.count()}")

        for pe_approval in queryset.iterator():
            self.stdout.write(
                f"pe_approval={pe_approval} start_at={pe_approval.start_at} "
                f"pe_state={pe_approval.pe_notification_status}"
            )
            if wet_run:
                pe_approval.notify_pole_emploi()
                sleep(delay)
