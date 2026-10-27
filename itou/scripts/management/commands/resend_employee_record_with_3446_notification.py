import datetime

from django.core.cache import caches
from django.db import transaction
from django.db.models import F
from itoutils.django.commands import dry_runnable

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecordUpdateNotification
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    BATCH_SIZE = 500

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        failsafe_cache = caches["failsafe"]
        cache_key = (
            f"resend_employee_record_with_3446_notification-{'wet_run' if wet_run else 'dry_run'}-last_notification_pk"
        )
        last_run_pk = failsafe_cache.get(cache_key) or 0
        self.logger.info("Starting resending employee records - starting at pk=%d", last_run_pk)
        processed_record_ids = set()
        newly_ready = 0
        rejected_notifications = list(
            EmployeeRecordUpdateNotification.objects.filter(
                # Rejected notification with error "Le PASS IAE n'est pas connu"
                status=NotificationStatus.REJECTED,
                asp_processing_code=EmployeeRecordUpdateNotification.ASP_UNKNOWN_APPROVAL_CODE,
                # Employee record marked as Intégrée
                employee_record__status=Status.PROCESSED,
                # And the notification error happened after the initial record processing
                created_at__gte=F("employee_record__processed_at"),
                # Start from last run
                pk__gt=last_run_pk,
            )
            .select_related("employee_record")
            .defer("employee_record__watched_data_updated_at")  # select_related doesn't use the model manager
            .select_for_update(of=("employee_record",), no_key=True)
            .order_by("pk")[: self.BATCH_SIZE]
        )
        for notification in rejected_notifications:
            # If 2 notifications share the same record, only call ready once
            if notification.employee_record.pk not in processed_record_ids:
                try:
                    with transaction.atomic():
                        notification.employee_record.ready()
                except Exception:
                    self.logger.warning(
                        "Could not transition employee_record=%d to READY", notification.employee_record.pk
                    )
                else:
                    newly_ready += 1
                processed_record_ids.add(notification.employee_record.pk)
        self.logger.info("Changed %d employee records to READY status", newly_ready)

        # When all employee records have been processed, restart from 0 to handle newly created notifications
        last_migrated_pk = rejected_notifications[-1].pk if rejected_notifications else 0
        failsafe_cache.set(cache_key, last_migrated_pk, timeout=datetime.timedelta(days=1).total_seconds())
        self.logger.info("Stored last migrated employee record notification - pk=%d", last_migrated_pk)
