# flake8: noqa
# pylint: disable=[logging-fstring-interpolation, singleton-comparison]

import csv
import datetime
import logging
import uuid
from pathlib import Path

import pandas as pd
import unidecode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from tqdm import tqdm

from itou.approvals.models import Approval
from itou.asp.models import Commune
from itou.common_apps.address.departments import department_from_postcode
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.models import Siae
from itou.users.models import User
from itou.utils.validators import validate_nir


# Columns
APPROVAL_COL = "agr_numero_agrement"
BIRTHDATE_COL = "pph_date_naissance"
BIRTHCITY_INSEE_COL = "code_insee_naissance"
CITY_INSEE_COL = "codeinseecom"
CONTRACT_STARTDATE_COL = "ctr_date_embauche"
CONTRACT_ENDDATE_COL = "ctr_date_fin_reelle"
COUNTRY_COL = "adr_code_insee_pays"
EMAIL_COL = "adr_mail"
FIRST_NAME_COL = "pph_prenom"
GENDER_COL = "pph_sexe"
LAST_NAME_COL = "pph_nom_usage"
NIR_COL = "ppn_numero_inscription"
PHONE_COL = "adr_telephone"
POST_CODE_COL = "codepostalcedex"
SIAE_NAME_COL = "pmo_denom_soc"
SIRET_COL = "pmo_siret"
PASS_IAE_NUMBER_COL = "Numéro de PASS IAE"
USER_PK = "ID utilisateur"

DATE_FORMAT = "%Y-%m-%d"


class Command(BaseCommand):
    """
    On December 1st, 2021, every AI were asked to present a PASS IAE for each of their employees.
    Before that date, they were able to hire without one. To catch up with the ongoing stock,
    the platform has to create missing users and deliver brand new PASS IAE.
    AI employees list was provided by the ASP in a CSV file.

    This is what this script does:
    1/ Parse a file provided by the ASP.
    2/ Clean data.
    3/ Create job seekers, approvals and job applications when needed.

    Mandatory arguments
    -------------------
    File path: path to the CSV file.
    django-admin import_ai_employees --file-path=/imports/file.csv

    Developer email: email of the person running this script. It must belong to
    a user account registered in the database.
    Job applications, users and approvals will be marked as created by this person.
    django-admin import_ai_employees --email=funky@developer.com

    Optional arguments
    ------------------
    Run without writing to the database:
    django-admin import_ai_employees --dry-run

    Run with a small amount of data (sample):
    django-admin import_ai_employees --sample-size=100

    """

    help = "Import AI employees and deliver a PASS IAE."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Don't change anything in the database."
        )
        parser.add_argument(
            "--sample-size",
            dest="sample_size",
            help="Sample size to run this script with (instead of the whole file).",
        )
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the CSV file to import",
        )
        parser.add_argument(
            "--email",
            dest="developer_email",
            required=True,
            action="store",
            help="Developer email account (in the Itou database).",
        )

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity >= 1:
            self.logger.setLevel(logging.DEBUG)

    def get_ratio(self, first_value, second_value):
        return round((first_value / second_value) * 100, 2)

    def fix_dates(self, date):
        # This is quick and ugly!
        if date.startswith("16"):
            return date[0] + "9" + date[2:]
        return date

    def log_to_csv(self, csv_name, logs):
        csv_file = Path(settings.EXPORT_DIR) / f"{csv_name}.csv"
        with open(csv_file, "w", newline="") as file:
            if isinstance(logs, list):
                fieldnames = list(logs[0].keys())
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(logs)
            else:
                file.write(logs.to_csv())

    def clean_nir(self, row):
        nir = row[NIR_COL]
        try:
            validate_nir(nir)
        except ValidationError:
            return None
        return nir

    def siret_is_valid(self, row):
        # ASP-validated list.
        excluded_sirets = [
            "88763724700016",
            "34536738700031",
            "82369160500013",
            "49185002000026",
            "33491197100029",
            "43196860100887",
            "47759309900054",
            "34229040000031",
            "89020637800014",
            "40136283500035",
            "88309441900024",
            "34526210900043",
            "35050254800034",
            "48856661300045",
            "81054375100012",
            "39359706700023",
            "38870926300023",
            "38403628100010",
            "37980819900010",
            "42385382900129",
            "43272738600018",
            "34280044800033",
            "51439409700018",
            "50088443200054",
            "26300199200019",
            "38420642100040",
            "33246830500021",
            "75231474000016",
            "34112012900034",
        ]
        return row[SIRET_COL] not in excluded_sirets

    def fake_email(self):
        return f"{uuid.uuid4().hex}@email-temp.com"

    def get_inexistent_structures(self, df):
        unique_ai = set(df[SIRET_COL])  # Between 600 and 700.
        existing_structures = Siae.objects.filter(siret__in=unique_ai, kind=Siae.KIND_AI).values_list(
            "siret", flat=True
        )
        not_existing_structures = unique_ai.difference(existing_structures)
        self.logger.debug(f"{len(not_existing_structures)} not existing structures:")
        self.logger.debug(not_existing_structures)
        return not_existing_structures

    def drop_excluded_structures(self, df, cleaned_df):
        df = df.copy()
        cleaned_df = cleaned_df.copy()
        # List provided by the ASP.
        inexistent_structures = cleaned_df[~cleaned_df.siret_is_valid]
        self.logger.info(f"Inexistent structures: excluding {len(inexistent_structures)} rows.")
        cleaned_df = cleaned_df.drop(inexistent_structures.index)
        df.loc[
            inexistent_structures.index, "Commentaire"
        ] = "Ligne ignorée : entreprise inexistante communiquée par l'ASP."

        # Remaining inexistent SIRETS.
        inexisting_sirets = self.get_inexistent_structures(cleaned_df)
        inexistent_structures = cleaned_df[cleaned_df[SIRET_COL].isin(inexisting_sirets)]
        self.logger.info(f"Inexistent structures: excluding {len(inexistent_structures)} rows.")
        cleaned_df = cleaned_df.drop(inexistent_structures.index)
        df.loc[inexistent_structures.index, "Commentaire"] = "Ligne ignorée : entreprise inexistante."

        return df, cleaned_df

    def import_data_into_itou(self, original_df, cleaned_df):
        original_df = original_df.copy()
        cleaned_df = cleaned_df.copy()

        created_users = 0
        ignored_nirs = 0
        already_existing_approvals = 0
        created_approvals = 0
        created_job_applications = 0

        # Get developer account by email.
        # Used to store who created the following users, approvals and job applications.
        developer = User.objects.get(email=self.developer_email)

        pbar = tqdm(total=len(cleaned_df))
        for i, row in cleaned_df.iterrows():
            pbar.update(1)

            with transaction.atomic():
                # Get city by its INSEE code to fill in the `User.city` attribute with a valid name.
                try:
                    commune = Commune.objects.current().get(code=row[CITY_INSEE_COL])
                except Commune.DoesNotExist:
                    # Communes stores the history of city names and INSEE codes.
                    # Sometimes, a commune is found twice but with the same name.
                    # As we just need a human name, we can take the first one.
                    commune = Commune.objects.filter(code=row[CITY_INSEE_COL]).first()
                except Commune.MultipleObjectsReturned:
                    commune = Commune.objects.current().filter(code=row[CITY_INSEE_COL]).first()
                else:
                    commune = Commune.objects.current().get(code=row[CITY_INSEE_COL])

                if row[CITY_INSEE_COL] == "01440":
                    # Veyziat has been merged with Oyonnax.
                    commune = Commune(name="Veyziat", code="01283")

                # Data has been formatted previously.
                user_data = {
                    "first_name": row[FIRST_NAME_COL].title(),
                    "last_name": row[LAST_NAME_COL].title(),
                    "birthdate": row[BIRTHDATE_COL],
                    # If no email: create a fake one.
                    "email": row[EMAIL_COL] or self.fake_email(),
                    "address_line_1": f"{row['adr_numero_voie']} {row['codeextensionvoie']} {row['codetypevoie']} {row['adr_libelle_voie']}",
                    "address_line_2": f"{row['adr_cplt_distribution']} {row['adr_point_remise']}",
                    "post_code": row[POST_CODE_COL],
                    "city": commune.name.title(),
                    "department": department_from_postcode(row[POST_CODE_COL]),
                    "phone": row[PHONE_COL],
                    "nir": row[NIR_COL],
                }

                # If NIR is not valid, row[NIR_COL] is empty.
                # See `self.clean_nir`.
                if not row.nir_is_valid:
                    ignored_nirs += 1

                job_seeker = User.objects.filter(nir=row[NIR_COL]).first()
                if not job_seeker:
                    job_seeker = User.objects.filter(email=row[EMAIL_COL]).first()

                # Some e-mail addresses belong to prescribers!
                if job_seeker and not job_seeker.is_job_seeker:
                    # If job seeker is not a job seeker, create a new one.
                    user_data["email"] = self.fake_email()
                    job_seeker = None

                # Create a job seeker.
                if not job_seeker:
                    created_users += 1
                    if self.dry_run:
                        job_seeker = User(**user_data)
                    else:
                        job_seeker = User.create_job_seeker_by_proxy(developer, **user_data)

                # If job seeker has already a valid approval: don't redeliver it.
                if job_seeker.approvals.valid().exists():
                    already_existing_approvals += 1
                    approval = job_seeker.approvals_wrapper.latest_approval
                else:
                    # create_employee_record will prevent "Fiche salariés" from being created.
                    approval = Approval(
                        start_at=datetime.date(2021, 12, 1),
                        end_at=datetime.date(2023, 11, 30),
                        user_id=job_seeker.pk,
                        created_by=developer,
                        create_employee_record=False,
                    )
                    created_approvals += 1
                    if not self.dry_run:
                        # `Approval.save()` delivers an automatic number.
                        approval.save()
                        # Make sure approval.pk is set.
                        approval.refresh_from_db()

                # Create a new job application.
                siae = Siae.objects.get(kind=Siae.KIND_AI, siret=row[SIRET_COL])
                job_app_dict = {
                    "sender": siae.active_admin_members.first(),
                    "sender_kind": JobApplication.SENDER_KIND_SIAE_STAFF,
                    "sender_siae": siae,
                    "to_siae": siae,
                    "job_seeker": job_seeker,
                    "state": JobApplicationWorkflow.STATE_ACCEPTED,
                    "hiring_start_at": row[CONTRACT_STARTDATE_COL],
                    "approval_delivery_mode": JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
                    "approval_id": approval.pk,
                    "approval_manually_delivered_by": developer,
                }
                job_application = JobApplication(**job_app_dict)
                created_job_applications += 1
                if not self.dry_run:
                    job_application.save()

            # Update dataframe values.
            # https://stackoverflow.com/questions/25478528/updating-value-in-iterrow-for-pandas
            cleaned_df.loc[i, PASS_IAE_NUMBER_COL] = approval.number
            cleaned_df.loc[i, USER_PK] = job_seeker.pk
            original_df.loc[i, PASS_IAE_NUMBER_COL] = approval.number

        self.logger.info("Import is over!")
        self.logger.info(f"Created users: {created_users}.")
        self.logger.info(f"Ignored NIRs: {ignored_nirs}.")
        self.logger.info(f"Already existing approvals: {already_existing_approvals}.")
        self.logger.info(f"Created approvals: {created_approvals}.")
        self.logger.info(f"Created job applications: {created_job_applications}.")

        return original_df, cleaned_df

    def create_emailing_file(self, df):
        emailing_rows = []

        for _, row in df.iterrows():
            siae = Siae.objects.prefetch_related("memberships__user").get(kind=Siae.KIND_AI, siret=row[SIRET_COL])
            admin = siae.active_admin_members.first()
            admin_address = admin.email if admin else ""
            emailing_row = {
                "Nom SIAE": siae.display_name,
                "Administrateur": admin_address,
                "Structure active ?": siae.is_active,
                "SIRET": row[SIRET_COL],
                "Prénom employé": row[FIRST_NAME_COL],
                "Nom employé": row[LAST_NAME_COL],
                "PASS IAE": row[PASS_IAE_NUMBER_COL],
            }

            if not self.dry_run:
                approval = Approval.objects.prefetch_related("user").get(number=row[PASS_IAE_NUMBER_COL])
                job_seeker = approval.user
                emailing_row = emailing_row | {
                    "PASS IAE début": approval.start_at,
                    "PASS IAE fin": approval.end_at,
                    "Prénom employé": job_seeker.first_name,
                    "Nom employé": job_seeker.last_name,
                    "Email employé": job_seeker.email,
                }
            emailing_rows.append(emailing_row)

        self.log_to_csv("emailing", emailing_rows)

    def handle(self, file_path, developer_email, dry_run=False, **options):
        """
        Each line represents a contract.
        1/ Read the file and clean data.
        2/ Exclude ignored rows.
        3/ Create job seekers, approvals and job applications.
        """
        self.dry_run = dry_run
        self.developer_email = developer_email
        sample_size = options.get("sample_size")
        self.set_logger(options.get("verbosity"))

        self.logger.info("Starting. Good luck…")
        self.logger.info("-" * 80)

        if sample_size:
            df = pd.read_csv(file_path, dtype=str, encoding="latin_1").sample(int(sample_size))
        else:
            df = pd.read_csv(file_path, dtype=str, encoding="latin_1")

        # Add a comment column to document why it may be removed.
        # Will be shared with the ASP.
        df["Commentaire"] = ""

        # Add an "approval" column to share with the ASP the PASS IAE number.
        df[PASS_IAE_NUMBER_COL] = ""
        df[USER_PK] = ""

        # Step 1: clean data
        self.logger.info("✨ STEP 1: clean data!")
        df[BIRTHDATE_COL] = df[BIRTHDATE_COL].apply(self.fix_dates)
        df[BIRTHDATE_COL] = pd.to_datetime(df[BIRTHDATE_COL], format=DATE_FORMAT)
        df[CONTRACT_STARTDATE_COL] = pd.to_datetime(df[CONTRACT_STARTDATE_COL], format=DATE_FORMAT)
        df[NIR_COL] = df.apply(self.clean_nir, axis=1)
        df["nir_is_valid"] = ~df[NIR_COL].isnull()
        df["siret_is_valid"] = df.apply(self.siret_is_valid, axis=1)

        # Users with invalid NIRS are stored but without a NIR.
        invalid_nirs = df[~df.nir_is_valid]
        df.loc[invalid_nirs.index, "Commentaire"] = "NIR invalide. Utilisateur potentiellement créé sans NIR."

        # Replace empty values by "" instead of NaN.
        df = df.fillna("")

        self.logger.info("🚮 STEP 2: remove rows!")
        cleaned_df = df.copy()

        # Exclude ended contracts.
        ended_contracts = cleaned_df[cleaned_df[CONTRACT_ENDDATE_COL] != ""]
        cleaned_df = cleaned_df.drop(ended_contracts.index)
        self.logger.info(f"Ended contract: excluding {len(ended_contracts)} rows.")
        df.loc[ended_contracts.index, "Commentaire"] = "Ligne ignorée : contrat terminé."

        # Exclude inexistent SIAE.
        df, cleaned_df = self.drop_excluded_structures(df, cleaned_df)

        # Exclude rows with an approval.
        rows_with_approval = cleaned_df[cleaned_df[APPROVAL_COL] != ""]
        cleaned_df = cleaned_df.drop(rows_with_approval.index)
        self.logger.info(f"Existing approval: excluding {len(rows_with_approval)} rows.")
        df.loc[rows_with_approval.index, "Commentaire"] = "Ligne ignorée : agrément ou PASS IAE renseigné."

        self.logger.info(
            f"Continuing with {len(cleaned_df)} rows left ({self.get_ratio(len(cleaned_df), len(df))} %)."
        )

        # Step 3: import data.
        self.logger.info("🔥 STEP 3: create job seekers, approvals and job applications.")
        df, cleaned_df = self.import_data_into_itou(original_df=df, cleaned_df=cleaned_df)

        # Step 4: create a CSV file including comments to be shared with the ASP.
        df = df.drop([USER_PK, "nir_is_valid", "siret_is_valid"], axis=1)  # Remove useless columns.
        self.log_to_csv("fichier_final", df)
        self.logger.info("📖 STEP 4: log final results.")
        self.logger.info("You can transfer this file to the ASP: /exports/import_ai_bilan.csv")

        # STEP 5: file to be used by the communication team in a mailing.
        self.create_emailing_file(cleaned_df)
        self.logger.info("📖 STEP 5: export data for emailing.")
        self.logger.info("Emailing file: /exports/emailing.csv")

        self.logger.info("-" * 80)
        self.logger.info("👏 Good job!")
