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


def create_logs(notification, from_state):
    # XXX: from_state can be PROCESSED, SENT or DISABLED (according to the trigger definition)
    # It might be simpler to always put PROCESSED.
    return [
        EmployeeRecordTransitionLog(
            timestamp=notification.created_at,
            from_state=from_state,
            to_state=Status.UPDATE_PENDING,
            transition=EmployeeRecordTransition.PLAN_UPDATE,
            recovered=True,
        ),
        EmployeeRecordTransitionLog(
            timestamp=EmployeeRecordBatch.datetime_from_asp_batch_file(notification.asp_batch_file),
            from_state=Status.UPDATE_PENDING,
            to_state=Status.UPDATE_SENT,
            transition=EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE_FOR_UPDATE,
            recovered=True,
        ),
        EmployeeRecordTransitionLog(
            timestamp=notification.updated_at,
            from_state=Status.UPDATE_SENT,
            to_state=(
                Status.PROCESSED if notification.status == NotificationStatus.PROCESSED else Status.UPDATE_REJECTED
            ),
            transition=(
                EmployeeRecordTransition.PROCESS
                if notification.status == NotificationStatus.PROCESSED
                else EmployeeRecordTransition.REJECT_FOR_UPDATE
            ),
            recovered=True,
        ),
    ]


class Command(BaseCommand):
    """Create the EmployeeRecordTransitionLog matching the EmployeeRecordUpdateNotification"""

    ATOMIC_HANDLE = True
    BATCH_SIZE = 1_000

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true", dest="wet_run")
        parser.add_argument("--only-processed", action="store_true", dest="only_processed")

    @dry_runnable
    def handle(self, *, only_processed, **options):
        if only_processed:
            matching_status = {NotificationStatus.PROCESSED}
        else:
            matching_status = {NotificationStatus.REJECTED, NotificationStatus.PROCESSED}

        logs_to_create = []
        notification_ids_to_delete = []
        for employee_record in (
            EmployeeRecord.objects.filter(
                Exists(
                    EmployeeRecordUpdateNotification.objects.filter(
                        employee_record=OuterRef("pk"),
                        status__in=matching_status,
                    )
                )
            )
            .exclude(asp_batch_file="")
            .order_by("pk")
            .prefetch_related("logs")  # XXX: only useful if we want to try to compute the "true" from_state/to_state
            .prefetch_related(
                Prefetch(
                    "update_notifications", queryset=EmployeeRecordUpdateNotification.objects.order_by("created_at")
                )
            )[: self.BATCH_SIZE]
        ):
            last_notification = None
            for notification in employee_record.update_notifications.all():
                if only_processed and notification.status == NotificationStatus.REJECTED:
                    continue
                logs_to_create.extend(create_logs(notification, from_state=Status.PROCESSED))
                notification_ids_to_delete.append(notification.pk)
                last_notification = notification

            if (
                last_notification and last_notification.status == NotificationStatus.REJECTED
            ):  # only_processed has to be False
                if all(last_notification.updated_at > log.timestamp for log in employee_record.logs.all()):
                    employee_record = EmployeeRecord.objects.select_for_update().get(
                        pk=employee_record
                    )  # Make sure we don't overwrite a changing status
                    employee_record.status = Status.UPDATE_REJECTED
                    employee_record.save(update_fields=("status", "updated_at"))

        EmployeeRecordTransitionLog.objects.bulk_create(logs_to_create)
        EmployeeRecordUpdateNotification.objects.filter(pk__in=notification_ids_to_delete).delete()
        # XXX: add logs
