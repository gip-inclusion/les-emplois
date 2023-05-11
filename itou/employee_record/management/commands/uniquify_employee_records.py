from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from itou.employee_record.models import EmployeeRecord, Status


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    @transaction.atomic()
    def handle(self, *, wet_run, **options):
        self.stdout.write("Start to uniquify employee records")

        duplicates = (
            EmployeeRecord.objects.values("asp_id", "approval_number")
            .annotate(cnt=Count("pk"))
            .filter(cnt__gt=1)
            .order_by("-cnt", "asp_id", "approval_number")
        )
        self.stdout.write(f"Found {len(duplicates)} asp_id/approval_number pairs with multiple employee records")

        for duplicate in duplicates:
            asp_id, approval_number = duplicate["asp_id"], duplicate["approval_number"]
            self.stdout.write(f"Handle {asp_id=}/{approval_number=} pairs")

            employee_records = (
                EmployeeRecord.objects.filter(asp_id=asp_id, approval_number=approval_number)
                .order_by("pk")
                .values_list("pk", "status", "updated_at", named=True)
            )

            if {er.status for er in employee_records} == {Status.DISABLED}:  # Only DISABLED
                # The last one in use should be the last one modified
                keep = sorted(employee_records, key=lambda er: er.updated_at)[-1]
            else:  # n DISABLED, 1 of another status
                keep = [er for er in employee_records if er.status != Status.DISABLED][0]
            discard = [er for er in employee_records if er.pk not in keep]
            self.stdout.write(f" > Keeping {keep}, discarding {discard}")

            assert keep.updated_at > max(er.updated_at for er in discard), "The kept object is not the most recent one"
            if wet_run:
                _, deleted = (
                    EmployeeRecord.objects.filter(asp_id=asp_id, approval_number=approval_number)
                    .exclude(pk=keep.pk)
                    .delete()
                )
                self.stdout.write(f" > Successfully deleted: {deleted}")
