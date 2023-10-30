import django.db.transaction as transaction
from django.core.management.base import BaseCommand

from itou.companies import models as siaes_models
from itou.employee_record.models import EmployeeRecord


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--for-siae",
            type=int,
            required=True,
        )
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @transaction.atomic()
    def handle(self, for_siae, *, wet_run=False, **options):
        siae = siaes_models.Company.objects.filter(pk=for_siae).select_related("convention").first()
        if not siae:
            self.stderr.write(f"No SIAE found for pk={for_siae!r}.")
            return
        if not siae.convention:
            self.stderr.write(f"No convention exists for {siae=}!")
            return

        self.stderr.write(f"Clone orphans employee records of {siae=} {siae.siret=} {siae.convention.asp_id=}")

        orphans = EmployeeRecord.objects.filter(job_application__to_siae=siae).orphans()
        to_clone = (
            orphans.exclude(approval_number__in=EmployeeRecord.objects.for_siae(siae).values("approval_number"))
            .distinct("approval_number")
            .order_by("approval_number", "-job_application__hiring_start_at", "-pk")
        )
        self.stderr.write(f"{len(to_clone)}/{orphans.count()} orphans employee records will be cloned")

        if not wet_run:
            self.stderr.write("Option --wet-run was not used so nothing will be cloned.")
        for employee_record in to_clone:
            self.stdout.write(f"Cloning {employee_record.pk=}...")
            if not wet_run:
                continue

            try:
                employee_record_clone = employee_record.clone()
            except Exception as e:
                self.stdout.write(f"  Error when cloning {employee_record.pk=}: {e}")
            else:
                self.stdout.write(f"  Cloning was successful, {employee_record_clone.pk=}")

        self.stderr.write("Done!")
