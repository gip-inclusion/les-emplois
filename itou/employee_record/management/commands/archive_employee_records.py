from django.core.management.base import BaseCommand
from django.db import transaction

from itou.employee_record.models import EmployeeRecord


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    @transaction.atomic()
    def handle(self, wet_run=False, **options):
        self.stdout.write("Start archiving employee records")

        archivable = (
            EmployeeRecord.objects.archivable()
            .order_by("job_application__approval__end_at")
            .select_related("job_application__approval")
        )
        self.stdout.write(f"Found {len(archivable)} archivable employee record(s)")

        archived_employee_records = []
        # A bulk update will increase performance if there are a lot of employee records to update.
        # However, if there is no performance issue, it is preferable to keep the archiving
        # and validation logic in the model (update_as_archived).
        # Update: let's bulk, with a batch size of 100 records
        for employee_record in archivable:
            try:
                # Do not trigger a save() call on the object
                self.stdout.write(f"Archiving {employee_record.pk=}")
                employee_record.update_as_archived(save=False)
            except Exception as ex:
                self.stdout.write(f"Can't archive {employee_record.pk=} {ex=}")
            else:
                archived_employee_records.append(employee_record)

        self.stdout.write(f"{len(archived_employee_records)}/{len(archivable)} employee record(s) can be archived")

        if wet_run:
            updated = EmployeeRecord.objects.bulk_update(
                archived_employee_records,
                ["status", "updated_at", "archived_json"],
                batch_size=100,
            )
            self.stdout.write(
                f"{updated}/{len(archived_employee_records)}/{len(archivable)} employee record(s) were archived"
            )
