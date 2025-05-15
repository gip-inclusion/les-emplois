import logging

import pandas as pd
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from itou.approvals.models import Approval
from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.job_applications.enums import JobApplicationState
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
        df["num_pass_iae"] = df["PASS IAE"].str.replace(" ", "")
        df["debut_de_cddi"] = pd.to_datetime(df["Début de CDDI"], format=date_format).apply(lambda x: x.date())
        df["pass_maj"] = False
        df["commentaire"] = None
        df["date_debut_pass_iae"] = None

        job_applications_to_update = []
        approvals_to_update = []
        approvals_nb_with_errors = []
        company = Company.objects.get(pk=company_id)

        approvals_qs = Approval.objects.filter(number__in=df["num_pass_iae"])

        for i, row in df.iterrows():
            if row["num_pass_iae"] not in approvals_qs.values_list("number", flat=True):
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire"] = "PASS IAE inconnu."
                continue

            approval = approvals_qs.get(number=row["num_pass_iae"])
            # There should be only one.
            job_application_qs = approval.jobapplication_set.filter(
                to_company_id=company.id, state=JobApplicationState.ACCEPTED
            )
            df.loc[i, "date_debut_pass_iae"] = approval.start_at

            # Job seeker had an approval before being hired by this company.
            if approval.start_at < row["debut_de_cddi"]:
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire"] = "PASS IAE débutant avant la nouvelle date."
            # Employee record has been integrated in the ASP.
            elif job_application_qs.filter(employee_record__status=Status.PROCESSED).exists():
                pks = job_application_qs.values_list("pk", flat=True)
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire"] = f"Fiche salarié déjà créée pour les candidatures suivantes : {list(pks)}."
            elif approval.suspension_set.exists():
                approvals_nb_with_errors.append(row["num_pass_iae"])
                values = approval.suspension_set.values("start_at", "end_at")
                df.loc[i, "commentaire"] = f"Des suspensions existent. {values}"
            elif approval.prolongation_set.exists():
                approvals_nb_with_errors.append(row["num_pass_iae"])
                values = approval.prolongation_set.values("start_at", "end_at")
                df.loc[i, "commentaire"] = f"Des prolongations existent. {values}"
            else:
                approval.start_at = row["debut_de_cddi"]
                approval.updated_at = timezone.now()
                approvals_to_update.append(approval)
                df.loc[i, "date_debut_pass_iae"] = approval.start_at
                df.loc[i, "pass_maj"] = True
                try:
                    job_application = job_application_qs.get()
                    job_application.hiring_start_at = row["debut_de_cddi"]
                    job_application.updated_at = timezone.now()
                    job_applications_to_update.append(job_application)
                    df.loc[i, "commentaire"] = "Candidature mise à jour"
                except JobApplication.DoesNotExist:
                    df.loc[i, "commentaire"] = "Aucune candidature trouvée."
                except JobApplication.MultipleObjectsReturned:
                    df.loc[i, "commentaire"] = (
                        "Mise à jour de la candidature reliée au PASS impossible car il y en a plusieurs."
                    )

        self.logger.info(f"PASS pouvant être mis à jour : {len(approvals_to_update)}.")
        self.logger.info(f"PASS en erreur : {len(approvals_nb_with_errors)}.")
        self.logger.info(f"Candidatures à mettre à jour : {len(job_applications_to_update)}")

        df["date_debut_pass_iae"] = df["date_debut_pass_iae"].apply(lambda x: x.strftime(date_format) if x else "")
        df["debut_de_cddi"] = df["debut_de_cddi"].apply(lambda x: x.strftime(date_format))
        df["pass_maj"] = df["pass_maj"].astype(str)

        df.to_excel(
            f"{settings.EXPORT_DIR}/bulk_update_from_file.xlsx",
            index=False,
            columns=["num_pass_iae", "date_debut_pass_iae", "debut_de_cddi", "pass_maj", "commentaire"],
        )
        if wet_run:
            self.logger.info("Wet run! Here we go!")
            with transaction.atomic():
                Approval.objects.bulk_update(approvals_to_update, fields=["start_at", "updated_at"])
                JobApplication.objects.bulk_update(
                    job_applications_to_update, fields=["hiring_start_at", "updated_at"]
                )
            self.logger.info("All good!")
