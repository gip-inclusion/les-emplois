from django.db import transaction

from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("siae_id", type=int)
        parser.add_argument("--wet-run", action="store_true")

    @transaction.atomic()
    def handle(self, *, siae_id, wet_run, **options):
        siae = Company.objects.select_related("convention").get(pk=siae_id)
        self.stdout.write(
            f"Marking employee records to be resend: {siae.display_name} - {siae.siret} {siae.kind} - ID {siae.pk}"
        )

        if not siae.can_use_employee_record:
            self.stdout.write(f"{siae} can't uses employee records")
            return

        asp_siret = EmployeeRecord.siret_from_asp_source(siae)

        to_resend = (
            EmployeeRecord.objects.filter(
                # Only resend the ones that have been successful
                status=Status.PROCESSED,
                # For fine-grained control instead of working on all convention's siaes
                job_application__to_company=siae,
            )
            .exclude(
                # Only resend the employee records with a "bad" Siret:
                # - If the Siret match, the employee record should already be on the ASP side,
                #   resending it will most likely result in a duplicate error.
                # - If a SIAE is "absorbed" by another one, we only want to resend the employee record
                #   of the absorbed ones.
                siret=asp_siret,
            )
            .order_by("-created_at")
        )

        self.stdout.write(f"Found {len(to_resend)} employee record(s) to resend")

        employee_records = []
        for employee_record in to_resend:
            self.stdout.write(f"Marking {employee_record} to be resend")
            employee_record.siret = asp_siret
            employee_record.status = Status.READY
            employee_records.append(employee_record)

        if wet_run:
            updated = EmployeeRecord.objects.bulk_update(employee_records, {"siret", "status"})
            self.stdout.write(f"{updated}/{len(employee_records)} employee records(s) were marked to be resend")
        else:
            self.stdout.write(
                f"DRY RUN: {len(employee_records)} employee records(s) would have been marked to be resend"
            )
