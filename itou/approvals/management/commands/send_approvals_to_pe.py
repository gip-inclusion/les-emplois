from time import sleep

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.apis import enums as api_enums


# arbitrary value, set so that we don't run the cron for too long.
# if the delay is set to 1 second, then this would take approximately 20 seconds
MAX_APPROVALS_PER_RUN = 10


class Command(BaseCommand):
    help = "Regularly sends all 'pending' and 'should retry' approvals to PE"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--delay", action="store", dest="delay", default=0, type=int, choices=range(0, 5))

    def handle(self, *, wet_run, delay, **options):
        today = timezone.localdate()
        queryset = (
            approvals_models.Approval.objects.filter(
                # we will ignore any approval that starts after today anyway.
                start_at__lte=today,
                # those with no accepted job application would also fail and stay pending.
                # also removes the approvals without any job application yet.
                jobapplication__state=JobApplicationWorkflow.STATE_ACCEPTED,
                # those with no user will crash, but we don't have the case yet in the DB.
                pe_notification_status__in=[
                    api_enums.PEApiNotificationStatus.PENDING,
                    api_enums.PEApiNotificationStatus.SHOULD_RETRY,
                ],
            )
            # those with a no-nir, no-birthdate or no-name user are also removed from the queryset
            # in order not to block the cron. They will be picked up as soon as they are set.
            .exclude(
                Q(user__nir="")
                | Q(user__birthdate=None)
                # there are no such cases in the database at the time of writing, but it *might* happen.
                | Q(user__nir="")
                | Q(user__first_name="")
                | Q(user__last_name="")
            ).order_by("-start_at")
        )

        self.stdout.write(
            f"approvals needing to be sent count={queryset.count()}, batch count={MAX_APPROVALS_PER_RUN}"
        )

        for approval in queryset[:MAX_APPROVALS_PER_RUN]:
            self.stdout.write(
                f"approvals={approval} start_at={approval.start_at} pe_state={approval.pe_notification_status}"
            )
            if wet_run:
                approval.notify_pole_emploi()
                sleep(delay)
