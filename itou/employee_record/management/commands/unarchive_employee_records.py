import argparse

from django.db import transaction

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    # TODO(rsebille): Delete this management command in 2025

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "employee_list_file",
            type=argparse.FileType(mode="r"),
        )
        parser.add_argument("siae_id", type=int)
        parser.add_argument("--wet-run", action="store_true")

    @transaction.atomic()
    def handle(self, *, employee_list_file, siae_id, wet_run, **options):
        self.stdout.write("Start moving employee records from archive")

        employees = []
        for line in employee_list_file:
            cleaned_line = line.strip()
            if cleaned_line:
                employees.append(cleaned_line.split(","))

        for last_name, first_name in employees:
            employee_record = (
                EmployeeRecord.objects.filter(
                    status=Status.ARCHIVED,
                    job_application__to_company=siae_id,
                    job_application__job_seeker__last_name__icontains=last_name,
                    job_application__job_seeker__first_name__icontains=first_name.split()[0],
                )
                .order_by("created_at")
                .first()
            )
            if not employee_record:
                self.stdout.write(f"No employee record found: {last_name=} {first_name=}")
            else:
                self.stdout.write(f"Moving {employee_record} to {Status.NEW}")
                employee_record.status = Status.NEW
                if wet_run:
                    employee_record.save(update_fields=["status"])

        self.stdout.write("Finished moving employee records from archive")
