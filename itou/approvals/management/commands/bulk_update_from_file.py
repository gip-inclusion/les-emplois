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

    def handle(self, wet_run, file_path, **options):
        df = pd.read_excel(file_path)
        date_format = "%d/%m/%Y"
        df["num_pass_iae"] = df["PASS IAE"].str.replace(" ", "")
        df["debut_de_cddi"] = pd.to_datetime(df["Début de CDDI"], format=date_format).apply(lambda x: x.date())
        df["siret"] = df["SIRET"].astype(str).str.replace(" ", "")
        df["pass_maj"] = False
        df["candidature_maj"] = False
        df["commentaire PASS IAE"] = None
        df["commentaire candidature"] = None
        df["date_debut_pass_iae"] = None

        job_applications_to_update = []
        approvals_to_update = []
        approvals_nb_with_errors = []
        companies_qs = Company.objects.filter(siret__in=set(df["siret"].tolist())).values_list("siret", "pk")
        companies_siret_to_pk = {siret: pk for siret, pk in companies_qs}

        approvals_qs = Approval.objects.filter(number__in=df["num_pass_iae"])
        approvals = {approval.number: approval for approval in approvals_qs}

        for i, row in df.iterrows():
            update_job_application = False
            if not companies_siret_to_pk.get(row["siret"]):
                df.loc[i, "commentaire PASS IAE"] = "SIRET inconnu. Pas de modification possible."
                continue

            if row["num_pass_iae"] not in approvals:
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire PASS IAE"] = "PASS IAE inconnu."
                continue

            approval = approvals[row["num_pass_iae"]]
            # There should be only one.
            job_application_qs = approval.jobapplication_set.filter(
                to_company_id=companies_siret_to_pk[row["siret"]], state=JobApplicationState.ACCEPTED
            )
            df.loc[i, "date_debut_pass_iae"] = approval.start_at

            # Job seeker had an approval before being hired by this company.
            if approval.start_at < row["debut_de_cddi"]:
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire PASS IAE"] = "PASS IAE débutant avant la nouvelle date."
                update_job_application = True
            # Employee record has been integrated in the ASP.
            elif pks := job_application_qs.filter(employee_record__status=Status.PROCESSED).values_list(
                "pk", flat=True
            ):
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire PASS IAE"] = (
                    f"Fiche salarié déjà créée pour les candidatures suivantes : {list(pks)}."
                )
            elif values := approval.suspension_set.values("start_at", "end_at"):
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire PASS IAE"] = f"Des suspensions existent. {values}"
            elif values := approval.prolongation_set.values("start_at", "end_at"):
                approvals_nb_with_errors.append(row["num_pass_iae"])
                df.loc[i, "commentaire PASS IAE"] = f"Des prolongations existent. {values}"
            else:
                approval.start_at = row["debut_de_cddi"]
                approval.updated_at = timezone.now()
                approvals_to_update.append(approval)
                df.loc[i, "date_debut_pass_iae"] = approval.start_at
                df.loc[i, "pass_maj"] = True
                update_job_application = True

            if update_job_application:
                try:
                    job_application = job_application_qs.get()
                    job_application.hiring_start_at = row["debut_de_cddi"]
                    job_application.updated_at = timezone.now()
                    job_applications_to_update.append(job_application)
                    df.loc[i, "candidature_maj"] = True
                except JobApplication.DoesNotExist:
                    df.loc[i, "commentaire candidature"] = "Aucune candidature trouvée."
                except JobApplication.MultipleObjectsReturned:
                    df.loc[i, "commentaire candidature"] = (
                        "Mise à jour de la candidature reliée au PASS impossible car il y en a plusieurs."
                    )

        self.logger.info(f"PASS pouvant être mis à jour : {len(approvals_to_update)}.")
        self.logger.info(f"PASS en erreur : {len(approvals_nb_with_errors)}.")
        self.logger.info(f"Candidatures à mettre à jour : {len(job_applications_to_update)}")

        df["date_debut_pass_iae"] = df["date_debut_pass_iae"].apply(lambda x: x.strftime(date_format) if x else "")
        df["debut_de_cddi"] = df["debut_de_cddi"].apply(lambda x: x.strftime(date_format))
        df["pass_maj"] = df["pass_maj"].astype(str)
        df["candidature_maj"] = df["candidature_maj"].astype(str)

        df.to_excel(
            f"{settings.EXPORT_DIR}/bulk_update_from_file.xlsx",
            index=False,
            columns=[
                "num_pass_iae",
                "date_debut_pass_iae",
                "debut_de_cddi",
                "pass_maj",
                "candidature_maj",
                "commentaire PASS IAE",
                "commentaire candidature",
            ],
        )
        if wet_run:
            self.logger.info("Wet run! Here we go!")
            with transaction.atomic():
                Approval.objects.bulk_update(approvals_to_update, fields=["start_at", "updated_at"])
                JobApplication.objects.bulk_update(
                    job_applications_to_update, fields=["hiring_start_at", "updated_at"]
                )
            self.logger.info("All good!")
