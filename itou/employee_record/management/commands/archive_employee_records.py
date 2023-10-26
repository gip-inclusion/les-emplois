from django.db import transaction

from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    @transaction.atomic()
    def handle(self, *, wet_run, **options):
        self.stdout.write("Start archiving employee records")

        archivable = (
            EmployeeRecord.objects.archivable()
            .order_by("job_application__approval__end_at")
            .select_related("job_application__approval")
        )
        self.stdout.write(f"Found {len(archivable)} archivable employee record(s)")

        archived_employee_records = []
        for employee_record in archivable:
            self.stdout.write(f"Archiving {employee_record.pk=}")
            if wet_run:
                try:
                    employee_record.update_as_archived()
                except Exception as ex:
                    self.stdout.write(f"Can't archive {employee_record.pk=} {ex=}")
                else:
                    archived_employee_records.append(employee_record)

        self.stdout.write(f"{len(archived_employee_records)}/{len(archivable)} employee record(s) were archived")
