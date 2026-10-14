import datetime

from django.db.models import Exists, OuterRef
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.employee_record.enums import NotificationStatus
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
        total_created = 0
        for notification in (
            EmployeeRecordUpdateNotification.objects.filter(
                status=NotificationStatus.REJECTED,
                created_at__lte=timezone.now() - datetime.timedelta(days=7),
            )
            .exclude(asp_processing_code=EmployeeRecordUpdateNotification.ASP_UNKNOWN_APPROVAL_CODE)
            .exclude(
                Exists(
                    EmployeeRecordUpdateNotification.objects.filter(
                        employee_record=OuterRef("employee_record")
                    ).exclude(pk=OuterRef("pk"))
                )
            )
            .order_by("created_at")[: self.BATCH_SIZE]
        ):
            _, created = EmployeeRecordUpdateNotification.objects.update_or_create(
                employee_record_id=notification.employee_record_id,
                status=NotificationStatus.NEW,
                defaults={"updated_at": timezone.now},
            )
            total_created += int(created)
        self.logger.info("Recreated %d rejected employee record update notifications", total_created)
