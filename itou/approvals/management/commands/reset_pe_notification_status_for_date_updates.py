import datetime
import time

from django.contrib.admin import models as admin_models
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import Q

from itou.approvals.models import Approval
from itou.utils.apis import enums as api_enums


BATCH_SIZE = 1000
FIX_DEPLOYMENT_DATE = datetime.datetime(2023, 11, 28, 10, 0, 0, tzinfo=datetime.UTC)


def migrate(approvals_queryset):
    total_objects = approvals_queryset.count()
    print(f"To migrate: {total_objects}")

    batch = []
    migrated = 0
    for approval in approvals_queryset.only("pk").iterator():
        approval.pe_notification_status = api_enums.PEApiNotificationStatus.PENDING
        batch.append(approval)
        if len(batch) >= min(BATCH_SIZE, total_objects):
            Approval.objects.bulk_update(
                batch,
                fields=["pe_notification_status"],
            )
            migrated += len(batch)
            print(f"Migrated: {migrated}")
            batch = []
            time.sleep(1)
    if batch:
        Approval.objects.bulk_update(
            batch,
            fields=["pe_notification_status"],
        )
        migrated += len(batch)
        print(f"Migrated: {migrated}")


class Command(BaseCommand):
    """Migration script that should only be launched once"""

    def handle(self, **options):
        # approvals that were edited in the admin before the fix deployment
        print("Approvals modifed in admin")
        approval_ids = sorted(
            set(
                int(object_id)
                for object_id in admin_models.LogEntry.objects.filter(
                    action_flag=admin_models.CHANGE,
                    content_type=ContentType.objects.get_for_model(Approval),
                    action_time__lt=FIX_DEPLOYMENT_DATE,
                ).values_list("object_id", flat=True)
            )
        )
        migrate(
            Approval.objects.filter(
                pk__in=approval_ids,
                pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS,
            )
        )

        # approvals with at least one prolongation or suspension that were created before the fix deployment
        print("Approvals with suspension/prolongation")
        objects_to_update = Approval.objects.filter(
            Q(suspension__pk__isnull=False) | Q(prolongation__pk__isnull=False),
            pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS,
            created_at__lt=FIX_DEPLOYMENT_DATE,
        ).distinct()
        migrate(objects_to_update)
