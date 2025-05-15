import logging

import pandas as pd
from django.conf import settings

from itou.approvals.models import Approval
from itou.companies.models import Company
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )

        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the XLSX file to import",
        )

        parser.add_argument(
            "--company-id",
            action="store",
            dest="company_id",
        )

    def handle(self, wet_run, file_path, company_id, **options):
        df = pd.read_excel(file_path)
        date_format = "%d/%m/%Y"
        df["number"] = df["PASS IAE"].str.replace(" ", "")
        df["hiring_at"] = pd.to_datetime(df["Début de CDDI"], format=date_format).apply(lambda x: x.date())
        df["updated"] = False
        df["reason"] = None
        df["approval_start_at"] = None
        df["employee_record_id"] = None

        job_applications_to_update = []
        approvals_to_update = []
        approvals_nb_with_errors = []
        company = Company.objects.get(pk=company_id)

        approvals_qs = Approval.objects.filter(number__in=df["number"]).prefetch_related(
            "jobapplication_set", "jobapplication_set__employee_record"
        )

        for i, row in df.iterrows():
            if row["number"] not in approvals_qs.values_list("number", flat=True):
                approvals_nb_with_errors.append(row["number"])
                df.loc[i, "reason"] = "PASS IAE inconnu."
                continue

            approval = approvals_qs.get(number=row["number"])
            job_applications = approval.jobapplication_set.filter(to_company_id=company.id)
            df.loc[i, "approval_start_at"] = approval.start_at

            # Job seeker had an approval before being hired by this company.
            if approval.start_at < row["hiring_at"]:
                approvals_nb_with_errors.append(row["number"])
                df.loc[i, "reason"] = "PASS IAE débutant avant la nouvelle date."
            # Employee record has been integrated in the ASP.
            elif job_applications.filter(employee_record__updated_at__isnull=False).exists():
                approvals_nb_with_errors.append(row["number"])
                pks = job_applications.values_list("pk", flat=True)
                df.loc[i, "reason"] = f"Fiche salarié déjà créée pour les candidatures suivantes : {list(pks)}."
            elif approval.suspension_set.exists():
                approvals_nb_with_errors.append(row["number"])
                values = approval.suspension_set.values("start_at", "end_at")
                df.loc[i, "reason"] = f"Des suspensions existent. {values}"
            elif approval.prolongation_set.exists():
                approvals_nb_with_errors.append(row["number"])
                values = approval.prolongation_set.values("start_at", "end_at")
                df.loc[i, "reason"] = f"Des prolongations existent. {values}"
            else:
                approval.start_at = row["hiring_at"]
                for job_application in job_applications:
                    job_application.hiring_start_at = row["hiring_at"]
                    job_applications_to_update.append(job_application)
                approvals_to_update.append(approval)
                df.loc[i, "approval_start_at"] = approval.start_at
                df.loc[i, "updated"] = True

        self.logger.info(f"PASS pouvant être mis à jour : {len(approvals_to_update)}.")
        self.logger.info(f"PASS en erreur : {len(approvals_nb_with_errors)}.")
        self.logger.info(f"Candidatures à mettre à jour : {len(job_applications_to_update)}")

        df["approval_start_at"] = df["approval_start_at"].apply(lambda x: x.strftime(date_format) if x else "")
        df["hiring_at"] = df["hiring_at"].apply(lambda x: x.strftime(date_format))
        df["updated"] = df["updated"].astype(str)

        df.to_excel(
            f"{settings.EXPORT_DIR}/bulk_update_from_file.xlsx",
            index=False,
            columns=["number", "approval_start_at", "hiring_at", "updated", "reason"],
        )
        if wet_run:
            self.logger.info("Wet run! Here we go!")
            Approval.objects.bulk_update(approvals_to_update, fields=["start_at"])
            JobApplication.objects.bulk_update(job_applications_to_update, fields=["hiring_start_at"])
            self.logger.info("All good!")
