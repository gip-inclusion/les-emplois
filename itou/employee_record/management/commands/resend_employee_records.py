import enum

from django.db import transaction
from django.db.models import Q

from itou.companies.models import Company, SiaeFinancialAnnex
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class OnlyOption(enum.StrEnum):
    EMPLOYEE_RECORDS = "employee-records"
    FINANCIAL_ANNEX = "financial-annex"


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("siae_id", type=int)
        parser.add_argument("financial_annex_number", type=str)
        parser.add_argument("--only", choices=set(OnlyOption), action="extend", nargs="+", type=OnlyOption)
        parser.add_argument("--wet-run", action="store_true")

    @transaction.atomic()
    def handle(self, *, siae_id, financial_annex_number, only, wet_run, **options):
        only = set(only or OnlyOption)

        siae = Company.objects.select_related("convention").get(pk=siae_id)
        if not siae.can_use_employee_record:
            self.stdout.write(f"{siae} can't uses employee records")
            return
        annex = SiaeFinancialAnnex.objects.get(number=financial_annex_number)
        asp_siret = EmployeeRecord.siret_from_asp_source(siae)

        self.stdout.write("Marking employee records to be resend:")
        self.stdout.write(f"  For {siae.display_name} - {siae.siret} {siae.kind} - ID {siae.pk}")
        exclude_q = Q()
        if OnlyOption.EMPLOYEE_RECORDS in only:
            self.stdout.write(f"  Using Siret {asp_siret}")
            exclude_q &= Q(siret=asp_siret)
        if OnlyOption.FINANCIAL_ANNEX in only:
            self.stdout.write(f"  Using {annex} - {annex.state} ({annex.end_at:%Y-%m-%d}) - ID {annex.pk}")
            exclude_q &= Q(financial_annex__isnull=True) | Q(financial_annex=annex)

        to_resend = (
            EmployeeRecord.objects.filter(
                # Only resend the ones that have been successful
                status=Status.PROCESSED,
                # For fine-grained control instead of working on all convention's siaes
                job_application__to_company=siae,
            )
            .exclude(exclude_q)
            .select_related("financial_annex")
            .order_by("-created_at")
        )
        self.stdout.write(f"Found {len(to_resend)} employee record(s) needing to be updated")

        employee_records = []
        fields_to_update = set()
        for employee_record in to_resend:
            self.stdout.write(f"Checking {employee_record}")
            fields_updated = set()
            if OnlyOption.EMPLOYEE_RECORDS in only:
                if employee_record.siret != asp_siret:
                    # Only resend the employee records with a "bad" Siret:
                    # - If the Siret match, the employee record should already be on the ASP side,
                    #   resending it will most likely result in a duplicate error.
                    # - If a SIAE is "absorbed" by another one, we only want to resend the employee record
                    #   of the absorbed ones.
                    employee_record.siret = asp_siret
                    employee_record.status = Status.READY
                    fields_updated |= {"siret", "status"}

            if OnlyOption.FINANCIAL_ANNEX in only:
                if employee_record.financial_annex and employee_record.financial_annex != annex:
                    employee_record.financial_annex = annex
                    fields_updated |= {"financial_annex"}

            if fields_updated:
                employee_records.append(employee_record)
                fields_to_update |= fields_updated
                self.stdout.write(f"  Updated fields: {fields_to_update}")

        if wet_run:
            updated = EmployeeRecord.objects.bulk_update(employee_records, fields_to_update)
            self.stdout.write(f"{updated}/{len(employee_records)} employee record(s) were updated")
        else:
            self.stdout.write(
                f"DRY RUN: {len(employee_records)} employee record(s) would have seen their {fields_to_update} updated"
            )
