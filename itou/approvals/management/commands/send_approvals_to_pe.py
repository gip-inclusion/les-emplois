from time import sleep

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.apis import enums as api_enums


# arbitrary value, set so that we don't run the cron for too long.
# if the delay is set to 1 second, then this would take approximately 280 seconds
# Since the cron runs every 5 minutes, it should be fine
MAX_APPROVALS_PER_RUN = 140


class Command(BaseCommand):
    help = "Regularly sends all 'pending' and 'should retry' approvals to PE"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--delay", action="store", dest="delay", default=0, type=int, choices=range(0, 5))

    def handle(self, *, wet_run, delay, **options):
        today = timezone.localdate()

        # Check if approvals in ERROR on endpoint rech_individu are now linked to an user
        # with a pe_obfuscated_nir (meaning the error is likely to be fixed)
        approvals_models.Approval.objects.filter(
            pe_notification_status=api_enums.PEApiNotificationStatus.ERROR,
            pe_notification_endpoint=api_enums.PEApiEndpoint.RECHERCHE_INDIVIDU,
            user__jobseeker_profile__pe_obfuscated_nir__isnull=False,
        ).update(pe_notification_status=api_enums.PEApiNotificationStatus.PENDING)

        # Check if pending approvals are now READY to be sent
        approvals_models.Approval.objects.filter(
            pe_notification_status=api_enums.PEApiNotificationStatus.PENDING,
            start_at__lte=today,
            # those with no accepted job application would also fail and stay pending.
            # also removes the approvals without any job application yet.
            jobapplication__state=JobApplicationWorkflow.STATE_ACCEPTED,
        ).exclude(Q(user__nir="") | Q(user__birthdate=None) | Q(user__first_name="") | Q(user__last_name="")).update(
            pe_notification_status=api_enums.PEApiNotificationStatus.READY
        )
        approvals_models.CancelledApproval.objects.filter(
            pe_notification_status=api_enums.PEApiNotificationStatus.PENDING,
            start_at__lte=today,
        ).exclude(Q(user_nir="") | Q(user_birthdate=None) | Q(user_first_name="") | Q(user_last_name="")).update(
            pe_notification_status=api_enums.PEApiNotificationStatus.READY
        )

        # Send READY Approvals
        queryset = approvals_models.Approval.objects.filter(
            pe_notification_status__in=[
                api_enums.PEApiNotificationStatus.READY,
                api_enums.PEApiNotificationStatus.SHOULD_RETRY,
            ],
        ).order_by("-start_at")

        nb_approvals = queryset.count()
        self.stdout.write(f"approvals needing to be sent count={nb_approvals}, batch count={MAX_APPROVALS_PER_RUN}")
        nb_approvals_to_send = min(nb_approvals, MAX_APPROVALS_PER_RUN)

        for approval in queryset[:nb_approvals_to_send]:
            self.stdout.write(
                f"approvals={approval} start_at={approval.start_at} pe_state={approval.pe_notification_status}"
            )
            if wet_run:
                approval.notify_pole_emploi()
                sleep(delay)

        # Send READY CancelledApprovals
        batch_left = MAX_APPROVALS_PER_RUN - nb_approvals_to_send
        cancelled_queryset = approvals_models.CancelledApproval.objects.filter(
            pe_notification_status__in=[
                api_enums.PEApiNotificationStatus.READY,
                api_enums.PEApiNotificationStatus.SHOULD_RETRY,
            ],
        ).order_by("-start_at")
        self.stdout.write(
            f"cancelled approvals needing to be sent count={cancelled_queryset.count()}, batch count={batch_left}"
        )
        for cancelled_approval in cancelled_queryset[:batch_left]:
            self.stdout.write(
                f"cancelled_approval={cancelled_approval} start_at={cancelled_approval.start_at} "
                f"pe_state={cancelled_approval.pe_notification_status}"
            )
            if wet_run:
                cancelled_approval.notify_pole_emploi()
                sleep(delay)
