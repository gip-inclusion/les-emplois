import argparse

from itou.approvals.enums import Origin
from itou.approvals.models import Approval
from itou.employee_record.constants import EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "approvals_list_file",
            type=argparse.FileType(mode="r"),
        )
        parser.add_argument("siret", type=str, nargs="+")
        parser.add_argument("--wet-run", action="store_true")

    def handle(self, *, approvals_list_file, siret, wet_run=False, **options):
        approvals_number = []
        for line in approvals_list_file:
            approval_number = line.strip().replace(" ", "")
            if not approval_number:
                continue
            approvals_number.append(approval_number)

        self.stdout.write("PASS;SIRET;Information")
        for approval_number in sorted(set(approvals_number)):
            try:
                employee_record = EmployeeRecord.objects.get(siret__in=siret, approval_number=approval_number)
            except EmployeeRecord.DoesNotExist:
                try:
                    job_application = JobApplication.objects.select_related("to_company").get(
                        to_company__siret__in=siret, approval__number=approval_number
                    )
                except JobApplication.DoesNotExist:
                    siret_used = "+".join(siret)
                    if not Approval.objects.filter(number=approval_number).exists():
                        info = "PASS IAE inconnu"
                    else:
                        info = "Pas de candidature"
                except JobApplication.MultipleObjectsReturned:
                    info, siret_used = "Plusieurs candidatures", "+".join(siret)
                else:
                    siret_used = job_application.to_company.siret
                    if job_application.state != JobApplicationWorkflow.STATE_ACCEPTED:
                        info = "La candidature n'est pas en état 'acceptée'"
                    elif job_application.origin == Origin.AI_STOCK:
                        info = "Import AI"
                    elif not job_application.create_employee_record:
                        info = "Création désactivée"
                    elif (
                        job_application.hiring_start_at
                        and job_application.hiring_start_at < EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE.date()
                    ):
                        info = "Date de début du contrat avant l'interopérabilité"
                    elif (
                        JobApplication.objects.eligible_as_employee_record(job_application.to_company)
                        .filter(pk=job_application.pk)
                        .exists()
                    ):
                        info = "En attente de création"
                    else:
                        info = "-"
            except EmployeeRecord.MultipleObjectsReturned:
                info, siret_used = "Plusieurs FS", "+".join(siret)
            else:
                info, siret_used = employee_record.get_status_display(), employee_record.siret

            self.stdout.write(f"{approval_number};{siret_used};{info}")
