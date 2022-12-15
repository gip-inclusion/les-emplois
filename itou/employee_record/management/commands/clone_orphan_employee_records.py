import django.db.transaction as transaction
from django.core.management.base import BaseCommand

from itou.employee_record.models import EmployeeRecord
from itou.siaes import models as siaes_models


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--old-asp-id",
            type=int,
            required=True,
        )
        parser.add_argument(
            "--new-asp-id",
            type=int,
            required=True,
        )
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
            help="Just report, don't do anything",
        )

    @transaction.atomic()
    def handle(self, old_asp_id, new_asp_id, wet_run=False, **options):
        try:
            siaes_models.SiaeConvention.objects.get(asp_id=new_asp_id)
        except siaes_models.SiaeConvention.DoesNotExist:
            self.stderr.write(f"No convention exists with {new_asp_id=}!")
            return

        self.stderr.write(f"Clone orphans employee records from {old_asp_id=} to {new_asp_id=}")

        employee_records_to_clone = EmployeeRecord.objects.orphans().filter(asp_id=old_asp_id).order_by("pk")
        self.stderr.write(f"{len(employee_records_to_clone)} employee records will be cloned")

        if not wet_run:
            self.stderr.write("Option --wet-run was not used so nothing will be cloned.")
        for employee_record in employee_records_to_clone:
            self.stdout.write(f"Cloning {employee_record.pk=}...")
            if not wet_run:
                continue

            try:
                with transaction.atomic():
                    employee_record_clone = employee_record.clone_orphan(new_asp_id)
            except Exception as e:
                self.stdout.write(f"  Error when cloning {employee_record.pk=}: {e}")
            else:
                self.stdout.write(f"  Cloning was successful, {employee_record_clone.pk=}")

        self.stderr.write("Done!")
