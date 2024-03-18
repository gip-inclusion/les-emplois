import argparse
import csv

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.companies.models import SiaeConvention
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """Used to create employee records for approvals and EITI companies already known by the ASP"""

    CSV_SEPARATOR = ";"

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=argparse.FileType(mode="r"),
            help="The filled CSV file sent to ASP",
        )
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @transaction.atomic
    def handle(self, file, *, wet_run=False, **options):
        now = timezone.now()
        siret_to_siaes = {}
        siret_without_convention = set()

        for row in csv.DictReader(file, delimiter=self.CSV_SEPARATOR):
            approval_number = row["emplois_pass"]
            siret = row["pmo_siret"]

            if not approval_number:
                self.stdout.write(f"Ignoring row (no approval): {row}")
                continue
            if siret in siret_without_convention:
                self.stdout.write(f"Ignoring row (no convention): {row}")
                continue

            try:
                approval = Approval.objects.get(number=approval_number)
            except Approval.DoesNotExist:
                self.stdout.write(f"WARNING: Approval doesn't exist {approval_number=}")
                continue

            if siret not in siret_to_siaes:
                try:
                    convention = SiaeConvention.objects.prefetch_related("siaes").get(
                        kind=CompanyKind.EITI, siaes__siret=siret
                    )
                except SiaeConvention.DoesNotExist:
                    self.stdout.write(f"WARNING: No convention found for {siret=}")
                    siret_without_convention.add(siret)
                    continue
                else:
                    siret_to_siaes[siret] = list(convention.siaes.all())

            siaes = siret_to_siaes[siret]
            job_applications_qs = JobApplication.objects.accepted().filter(to_company__in=siaes, approval=approval)
            self.stdout.write(f"Found {len(job_applications_qs)} JA for {siret=} {approval=} {siaes=}")
            match len(job_applications_qs):
                case 0:  # 75 of the 3462 rows.
                    # We can't (not want) create an accepted job application from nothing,
                    # so let the employer figure it out and fix it, if it's even needed.
                    continue
                case 1:  # 2840 of the 3462 rows.
                    job_application = job_applications_qs.get()
                case _:  # 21 of the 3462 rows.
                    # If accepted job applications are:
                    # - In the same SIAE → get first hiring
                    # - In multiple SIAE → get first hiring in the matching Siret, the "mother" (SOURCE_ASP)
                    if len(siaes) > 1:
                        job_applications_qs = job_applications_qs.filter(to_company__siret=siret)
                    job_application = job_applications_qs.with_accepted_at().earliest("accepted_at")
            try:
                er = EmployeeRecord.from_job_application(job_application, clean=False)
            except ValidationError:
                self.stdout.write(f"INFO: An employee record already exists {siret=} {approval=}")
                continue

            try:
                er.clean()
            except ValidationError:  # Some information is missing
                # This will lead to "Un PASS IAE doit être unique pour un même SIRET" (3436) errors, but this will
                # avoid future notifications to return with error, better handling this when everyone expect it.
                er.status = Status.NEW
            else:  # Everything is fine
                er.status = Status.PROCESSED
            er.asp_processing_label = f'Statut forcé à "{er.status.label}" suite à la reprise de stock EITI'
            er.processed_at = now

            if wet_run:
                er.save()
                self.stdout.write(f"Saving {er}")
