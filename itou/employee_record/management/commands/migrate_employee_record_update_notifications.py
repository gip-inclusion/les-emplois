import datetime

from django.core.cache import caches
from django.db.models import Exists, OuterRef, Prefetch
from itoutils.django.commands import dry_runnable

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import (
    EmployeeRecord,
    EmployeeRecordBatch,
    EmployeeRecordTransition,
    EmployeeRecordTransitionLog,
    EmployeeRecordUpdateNotification,
)
from itou.utils.command import BaseCommand


def create_logs(employee_record, notification):
    logs = [
        EmployeeRecordTransitionLog(
            employee_record=employee_record,
            timestamp=notification.created_at,
            # This from_state is likely inconsistent with the other transitions, but simplify things
            from_state=Status.PROCESSED,
            to_state=Status.MODIFICATION_PENDING,
            transition=EmployeeRecordTransition.SCHEDULE_MODIFICATION,
            recovered=True,
        ),
        EmployeeRecordTransitionLog(
            employee_record=employee_record,
            timestamp=EmployeeRecordBatch.datetime_from_asp_batch_file(notification.asp_batch_file),
            from_state=Status.MODIFICATION_PENDING,
            to_state=Status.MODIFICATION_SENT,
            transition=EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
            recovered=True,
        ),
        EmployeeRecordTransitionLog(
            employee_record=employee_record,
            timestamp=notification.updated_at,
            from_state=Status.MODIFICATION_SENT,
            # This to_state is likely inconsistent with the other transitions, but simplify things
            to_state=(
                Status.PROCESSED
                if notification.status == NotificationStatus.PROCESSED
                else Status.MODIFICATION_REJECTED
            ),
            transition=(
                EmployeeRecordTransition.PROCESS_MODIFICATION
                if notification.status == NotificationStatus.PROCESSED
                else EmployeeRecordTransition.REJECT_MODIFICATION
            ),
            recovered=True,
        ),
    ]
    logs[1].set_asp_batch_information(
        notification.asp_batch_file,
        notification.asp_batch_line_number,
        notification.archived_json,
    )
    logs[2].set_asp_processing_information(
        notification.asp_processing_code,
        notification.asp_processing_label,
        notification.archived_json,
    )
    return logs


class Command(BaseCommand):
    """Create the EmployeeRecordTransitionLog matching the EmployeeRecordUpdateNotification"""

    ATOMIC_HANDLE = True
    BATCH_SIZE = 1_000

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true", dest="wet_run")
        parser.add_argument("--include-last-rejected", action="store_true", dest="include_last_rejected")

    @dry_runnable
    def handle(self, *, include_last_rejected, **options):
        migratable_statuses = {NotificationStatus.PROCESSED, NotificationStatus.REJECTED}

        failsafe_cache = caches["failsafe"]
        cache_key = f"migrate_employee_record_update_notifications-{include_last_rejected}-last_record_pk"
        last_run_pk = failsafe_cache.get(cache_key) or 0
        self.logger.info("Starting migrating employee records - starting at pk=%d", last_run_pk)

        logs_to_create = []
        notification_ids_to_delete = []
        employee_records = list(
            EmployeeRecord.objects.filter(
                Exists(
                    EmployeeRecordUpdateNotification.objects.filter(
                        employee_record=OuterRef("pk"),
                        status__in=migratable_statuses,
                    )
                )
            )
            .with_last_transition_timestamp()
            .filter(pk__gt=last_run_pk)
            .order_by("pk")
            .prefetch_related(
                Prefetch(
                    "update_notifications", queryset=EmployeeRecordUpdateNotification.objects.order_by("created_at")
                )
            )[: self.BATCH_SIZE]
        )

        for employee_record in employee_records:
            er_notifications = list(employee_record.update_notifications.all())
            reject_employee_record = False
            if er_notifications[-1].status == NotificationStatus.REJECTED and (
                not employee_record.last_transition_timestamp  # This shouldn't be possible
                or (er_notifications[-1].updated_at > employee_record.last_transition_timestamp)
            ):
                # This UpdateNotification implies to change the employee record status
                if include_last_rejected:
                    reject_employee_record = True
                else:
                    # Do not change the status yet, but keep the last update notification to change it later
                    er_notifications = er_notifications[:-1]

            for notification in er_notifications:
                if notification.status not in migratable_statuses:
                    continue
                logs_to_create.extend(create_logs(employee_record, notification))
                notification_ids_to_delete.append(notification.pk)

            if reject_employee_record:
                employee_record_to_update = EmployeeRecord.objects.select_for_update().get(
                    pk=employee_record.pk,
                )  # Make sure we don't overwrite a changing status
                if employee_record_to_update.status != employee_record.status:
                    self.logger.info(
                        "Status change of employee_record=%d skipped: its status changed recently", employee_record.pk
                    )
                    continue
                self.logger.info("Updating employee_record=%d status to MODIFICATION_REJECTED", employee_record.pk)
                employee_record_to_update.status = Status.MODIFICATION_REJECTED
                employee_record_to_update.save(update_fields=("status", "updated_at"))

        EmployeeRecordTransitionLog.objects.bulk_create(logs_to_create)
        EmployeeRecordUpdateNotification.objects.filter(pk__in=notification_ids_to_delete).delete()
        self.logger.info(
            "Migrated %d EmployeeRecordUpdateNotification to %d EmployeeRecordTransitionLog",
            len(notification_ids_to_delete),
            len(logs_to_create),
        )
        # When all employee records have been processed, restart from 0 to handle newly created notifications
        last_migrated_pk = employee_records[-1].pk if employee_records else 0
        failsafe_cache.set(cache_key, last_migrated_pk, timeout=datetime.timedelta(days=1).total_seconds())
        self.logger.info("Stored last migrated employee record - pk=%d", last_migrated_pk)
