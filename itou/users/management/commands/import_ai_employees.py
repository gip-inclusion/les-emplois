# flake8: noqa
# pylint: disable=logging-fstring-interpolation, singleton-comparison, invalid-name

import csv
import datetime
import re
import uuid
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from tqdm import tqdm

from itou.approvals.models import Approval
from itou.asp.models import Commune
from itou.common_apps.address.departments import department_from_postcode
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from itou.siaes.models import Siae
from itou.users.models import User
from itou.utils.management_commands import DeprecatedLoggerMixin
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
COMMENTS_COL = "commentaire"
USER_PK_COL = "salarie_id_pour_asp"
USER_ITOU_EMAIL_COL = "salarie_itou_email"
PASS_IAE_NUMBER_COL = "pass_iae_numero"
PASS_IAE_START_DATE_COL = "pass_iae_date_debut"
PASS_IAE_END_DATE_COL = "pass_iae_date_fin"

# First file.
DATE_FORMAT = "%Y-%m-%d"

# Second file.
# DATE_FORMAT = "%d/%m/%Y"


class Command(DeprecatedLoggerMixin, BaseCommand):
    """
    On December 1st, 2021, every AI were asked to present a PASS IAE for each of their employees.
    Before that date, they were able to hire without one. To catch up with the ongoing stock,
    the platform has to create missing users and deliver brand new PASS IAE.
    AI employees list was provided by the ASP in a CSV file.

    A fixed creation date (settings.AI_EMPLOYEES_STOCK_IMPORT_DATE) allows us to retrieve objects
    created by this script.
    See Approval.is_from_ai_stock for example.

    This is what this script does:
    1/ Parse a file provided by the ASP.
    2/ Clean data.
    3/ Create job seekers, approvals and job applications when needed.

    Mandatory argument
    -------------------
    File path: path to the CSV file.
    django-admin import_ai_employees --file-path=/imports/file.csv

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
            "--invalid-nirs-only",
            dest="invalid_nirs_only",
            action="store_true",
            help="Only save users whose NIR is invalid.",
        )

        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the CSV file to import",
        )

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

    def clean_email(self, row):
        """
        Some employers gave their email address instead of the job seeker's one.
        Delete them whenever possible.
        """
        row = row.fillna("")
        email = row[EMAIL_COL]
        if not email:
            return email
        siret = row[SIRET_COL]
        domain = re.search(r"@(\w+)", email).groups()[0]
        generic_domains = [
            "google",
            "yahoo",
            "laposte",
            "live",
            "orange",
            "icloud",
            "outlook",
            "wanadoo",
            "aol",
            "hotmail",
            "sfr",
            "neuf",
            "gmail",
            "free",
        ]
        if domain in generic_domains:
            return email
        siae_qs = Siae.objects.filter(kind=SiaeKind.AI, siret=siret)
        if not siae_qs.exists():
            return email
        siae = siae_qs.get()
        siae_domain = re.search(r"@(.*)$", siae.auth_email).groups()[0]
        if email.endswith(siae_domain):
            self.logger.info(f"Corporate email found: {email}.")
            return ""
        return email

    def siret_validated_by_asp(self, row):
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
        existing_structures = Siae.objects.filter(siret__in=unique_ai, kind=SiaeKind.AI).values_list(
            "siret", flat=True
        )
        not_existing_structures = unique_ai.difference(existing_structures)
        self.logger.debug(f"{len(not_existing_structures)} not existing structures:")
        self.logger.debug(not_existing_structures)
        return not_existing_structures

    def commune_from_insee_col(self, insee_code):
        try:
            commune = Commune.objects.current().get(code=insee_code)
        except Commune.DoesNotExist:
            # Communes stores the history of city names and INSEE codes.
            # Sometimes, a commune is found twice but with the same name.
            # As we just need a human name, we can take the first one.
            commune = Commune.objects.filter(code=insee_code).first()
        except Commune.MultipleObjectsReturned:
            commune = Commune.objects.current().filter(code=insee_code).first()
        else:
            commune = Commune.objects.current().get(code=insee_code)

        if insee_code == "01440":
            # Veyziat has been merged with Oyonnax.
            commune = Commune(name="Veyziat", code="01283")
        return commune

    def find_or_create_job_seeker(self, row, created_by):
        created = False
        # Get city by its INSEE code to fill in the `User.city` attribute with a valid name.
        commune = self.commune_from_insee_col(row[CITY_INSEE_COL])

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
            "date_joined": settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
        }

        # If NIR is not valid, row[NIR_COL] is empty.
        # See `self.clean_nir`.
        if not row.nir_is_valid:
            user_data["nir"] = None

        job_seeker = None
        if row.nir_is_valid:
            job_seeker = User.objects.filter(nir=user_data["nir"]).exclude(Q(nir__isnull=True) | Q(nir="")).first()

        if not job_seeker:
            job_seeker = User.objects.filter(email=user_data["email"]).first()

        if not job_seeker:
            # Find users created previously by this script,
            # either because a bug forced us to interrupt it
            # or because we had to run it twice to import new users.
            job_seeker = User.objects.filter(
                first_name=user_data["first_name"],
                last_name=user_data["last_name"],
                birthdate=user_data["birthdate"].date(),
                created_by=created_by,
                date_joined__date=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE.date(),
            ).first()

        # Some e-mail addresses belong to prescribers!
        if job_seeker:
            # Probably same corporate email.
            not_same_nir = job_seeker.nir and job_seeker.nir != row[NIR_COL]
            if not_same_nir:
                self.logger.info(f"User found but with a different NIR: {job_seeker.email}. Creating a new one.")
            if not job_seeker.is_job_seeker or not_same_nir:
                # If job seeker is not a job seeker, create a new one.
                user_data["email"] = self.fake_email()
                job_seeker = None

        if not job_seeker:
            if self.dry_run:
                job_seeker = User(**user_data)
            else:
                job_seeker = User.create_job_seeker_by_proxy(created_by, **user_data)
            created = True

        return created, job_seeker

    def find_or_create_approval(self, job_seeker, created_by):
        created = False
        redelivered_approval = False
        approval = None
        # If job seeker has already a valid approval: don't redeliver it.
        if job_seeker.approvals.valid().exists():
            approval = job_seeker.latest_approval
            # ...unless it was issued by an AI who did not want to wait for our script to run.
            job_app_qs = approval.jobapplication_set.filter(
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                to_siae=F("sender_siae"),
                created_at__gt=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
                approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC,
            )
            count = job_app_qs.count()
            if count == 1:
                self.logger.info(f"Approval delivered by employer: {approval.pk}. Deleting it.")
                self.logger.info(f"Job application sent by employer: {job_app_qs.get().pk}. Deleting it.")
                if not self.dry_run:
                    job_app_qs.delete()
                    approval.delete()
                approval = None
                redelivered_approval = True
            elif count > 1:
                self.logger.info(f"Multiple accepted job applications linked to this approval: {approval.pk}.")

        if not approval:
            # `create_employee_record` prevents "Fiche salariés" from being created.
            approval = Approval(
                start_at=datetime.date(2021, 12, 1),
                end_at=datetime.date(2023, 11, 30),
                user_id=job_seeker.pk,
                created_by=created_by,
                created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
            )
            if not self.dry_run:
                # In production, it can raise an IntegrityError if another PASS has just been delivered a few seconds ago.
                # Try to save with another number until it succeeds.
                succeeded = None
                while succeeded is None:
                    try:
                        # `Approval.save()` delivers an automatic number.
                        approval.save()
                        succeeded = True
                    except IntegrityError:
                        pass
            created = True
        return created, approval, redelivered_approval

    def find_or_create_job_application(self, approval, job_seeker, row, approval_manually_delivered_by):
        """Find job applications created previously by this script,
        either because a bug forced us to interrupt it
        or because we had to run it twice to import new users.
        """
        created = False
        cancelled_job_app_deleted = False
        siae = Siae.objects.prefetch_related("memberships").get(kind=SiaeKind.AI, siret=row[SIRET_COL])
        job_application_qs = JobApplication.objects.filter(
            to_siae=siae,
            approval_manually_delivered_by=approval_manually_delivered_by,
            created_at__date=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE.date(),
            job_seeker=job_seeker,
            hiring_start_at=row[CONTRACT_STARTDATE_COL],
        )

        # Employers cancelled job applications created by us with this script,
        # deleting at the same time the approval we issued.
        # Delete this job application to start from new.
        cancelled_job_application_qs = job_application_qs.filter(state=JobApplicationWorkflow.STATE_CANCELLED)
        if cancelled_job_application_qs.exists():
            if not self.dry_run:
                cancelled_job_application_qs.delete()
            cancelled_job_app_deleted = True

        if job_application_qs.exists():
            total_job_applications = job_application_qs.count()
            if total_job_applications != 1:
                # Make sure it's different contracts.
                job_applications_dates = job_application_qs.all().values_list("hiring_start_at", flat=True)
                if len(set(job_applications_dates)) != total_job_applications:
                    self.logger.info(
                        f"{job_application_qs.count()} job applications found for job_seeker: {job_seeker.email} - {job_seeker.pk}."
                    )

        job_application = job_application_qs.first()

        # Previously create job applications may still allow employee records creation.
        if job_application and job_application.create_employee_record:
            job_application.create_employee_record = False
            if not self.dry_run:
                job_application.save()
        if not job_application:
            job_app_dict = {
                "sender": siae.active_admin_members.first(),
                "sender_kind": SenderKind.SIAE_STAFF,
                "sender_siae": siae,
                "to_siae": siae,
                "job_seeker": job_seeker,
                "state": JobApplicationWorkflow.STATE_ACCEPTED,
                "hiring_start_at": row[CONTRACT_STARTDATE_COL],
                "approval_delivery_mode": JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
                "approval_id": approval.pk,
                "approval_manually_delivered_by": approval_manually_delivered_by,
                "created_at": settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
                "create_employee_record": False,
                "approval_number_sent_by_email": True,
            }
            job_application = JobApplication(**job_app_dict)
            if not self.dry_run:
                job_application.save()
            created = True
        return created, job_application, cancelled_job_app_deleted

    def import_data_into_itou(self, df, to_be_imported_df):
        df = df.copy()

        created_users = 0
        found_users = 0
        ignored_nirs = 0
        found_approvals = 0
        created_approvals = 0
        found_job_applications = 0
        created_job_applications = 0
        redelivered_approvals = 0
        cancelled_job_apps_deleted = 0

        # Get developer account by email.
        # Used to store who created the following users, approvals and job applications.
        developer = User.objects.get(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)

        pbar = tqdm(total=len(to_be_imported_df))
        for i, row in to_be_imported_df.iterrows():
            pbar.update(1)
            try:
                with transaction.atomic():
                    user_creation, job_seeker = self.find_or_create_job_seeker(row=row, created_by=developer)

                    if user_creation:
                        created_users += 1
                    else:
                        found_users += 1

                    approval_creation, approval, redelivered_approval = self.find_or_create_approval(
                        job_seeker=job_seeker, created_by=developer
                    )

                    if approval_creation:
                        created_approvals += 1
                    else:
                        found_approvals += 1

                    if redelivered_approval:
                        redelivered_approvals += 1

                    job_application_creation, _, cancelled_job_app_deleted = self.find_or_create_job_application(
                        approval=approval, job_seeker=job_seeker, row=row, approval_manually_delivered_by=developer
                    )
                    if job_application_creation:
                        created_job_applications += 1
                    else:
                        found_job_applications += 1

                    if cancelled_job_app_deleted:
                        cancelled_job_apps_deleted += 1
            except (ValidationError, IntegrityError) as e:
                self.logger.critical("ValidationError or IntegrityError during import: %s" % e)
                continue

            # Update dataframe values.
            # https://stackoverflow.com/questions/25478528/updating-value-in-iterrow-for-pandas
            df.loc[i, PASS_IAE_NUMBER_COL] = approval.number
            df.loc[i, PASS_IAE_START_DATE_COL] = approval.start_at.strftime(DATE_FORMAT)
            df.loc[i, PASS_IAE_END_DATE_COL] = approval.end_at.strftime(DATE_FORMAT)
            df.loc[i, USER_PK_COL] = job_seeker.jobseeker_hash_id
            df.loc[i, USER_ITOU_EMAIL_COL] = job_seeker.email

        self.logger.info("Import is over!")
        self.logger.info(f"Already existing users: {found_users}.")
        self.logger.info(f"Created users: {created_users}.")
        self.logger.info(f"Already existing approvals: {found_approvals}.")
        self.logger.info(f"Created approvals: {created_approvals}.")
        self.logger.info(f"Already existing job applications: {found_job_applications}.")
        self.logger.info(f"Created job applications: {created_job_applications}.")
        self.logger.info(f"Redelivered approvals: {redelivered_approvals}.")
        self.logger.info(f"Deleted previously canceled job applications: {cancelled_job_apps_deleted}.")

        return df

    def clean_df(self, df):
        df[BIRTHDATE_COL] = df[BIRTHDATE_COL].apply(self.fix_dates)
        df[BIRTHDATE_COL] = pd.to_datetime(df[BIRTHDATE_COL], format=DATE_FORMAT)
        df[CONTRACT_STARTDATE_COL] = pd.to_datetime(df[CONTRACT_STARTDATE_COL], format=DATE_FORMAT)
        df[NIR_COL] = df.apply(self.clean_nir, axis=1)
        df[EMAIL_COL] = df.apply(self.clean_email, axis=1)
        df["nir_is_valid"] = ~df[NIR_COL].isnull()
        df["siret_validated_by_asp"] = df.apply(self.siret_validated_by_asp, axis=1)

        # Replace empty values by "" instead of NaN.
        df = df.fillna("")
        return df

    def add_columns_for_asp(self, df):
        df[COMMENTS_COL] = ""
        df[USER_PK_COL] = ""
        df[USER_ITOU_EMAIL_COL] = ""
        df[PASS_IAE_NUMBER_COL] = ""
        df[PASS_IAE_START_DATE_COL] = ""
        df[PASS_IAE_END_DATE_COL] = ""
        return df

    def filter_invalid_nirs(self, df):
        total_df = df.copy()
        invalid_nirs_df = total_df[~total_df.nir_is_valid].copy()
        comment = "NIR invalide. Utilisateur potentiellement créé sans NIR."
        total_df.loc[invalid_nirs_df.index, COMMENTS_COL] = comment
        invalid_nirs_df.loc[invalid_nirs_df.index, COMMENTS_COL] = comment
        return total_df, invalid_nirs_df

    def remove_ignored_rows(self, total_df):
        # Exclude ended contracts.
        total_df = total_df.copy()
        filtered_df = total_df.copy()

        if CONTRACT_ENDDATE_COL in total_df.columns:
            ended_contracts = total_df[total_df[CONTRACT_ENDDATE_COL] != ""]
            filtered_df = filtered_df.drop(ended_contracts.index)
            self.logger.info(f"Ended contract: excluding {len(ended_contracts)} rows.")
            total_df.loc[ended_contracts.index, COMMENTS_COL] = "Ligne ignorée : contrat terminé."

        # List provided by the ASP.
        excluded_structures_df = filtered_df[~filtered_df.siret_validated_by_asp]
        self.logger.info(f"Inexistent structures: excluding {len(excluded_structures_df)} rows.")
        filtered_df = filtered_df.drop(excluded_structures_df.index)
        total_df.loc[
            excluded_structures_df.index, COMMENTS_COL
        ] = "Ligne ignorée : entreprise inexistante communiquée par l'ASP."

        # Inexistent SIRETS.
        inexisting_sirets = self.get_inexistent_structures(filtered_df)
        inexistent_structures_df = filtered_df[filtered_df[SIRET_COL].isin(inexisting_sirets)]
        self.logger.info(f"Inexistent structures: excluding {len(inexistent_structures_df)} rows.")
        filtered_df = filtered_df.drop(inexistent_structures_df.index)
        total_df.loc[inexistent_structures_df.index, COMMENTS_COL] = "Ligne ignorée : entreprise inexistante."

        # Exclude rows with an approval.
        rows_with_approval_df = filtered_df[filtered_df[APPROVAL_COL] != ""]
        filtered_df = filtered_df.drop(rows_with_approval_df.index)
        self.logger.info(f"Existing approval: excluding {len(rows_with_approval_df)} rows.")
        total_df.loc[rows_with_approval_df.index, COMMENTS_COL] = "Ligne ignorée : agrément ou PASS IAE renseigné."
        return total_df, filtered_df

    def handle(self, file_path, dry_run=False, invalid_nirs_only=False, **options):
        """
        Each line represents a contract.
        1/ Read the file and clean data.
        2/ Exclude ignored rows.
        3/ Create job seekers, approvals and job applications.
        """
        self.dry_run = dry_run
        sample_size = options.get("sample_size")
        self.set_logger(options.get("verbosity"))

        self.logger.info("Starting. Good luck…")
        self.logger.info("-" * 80)

        if sample_size:
            df = pd.read_csv(file_path, dtype=str, encoding="latin_1", sep=";").sample(int(sample_size))
        else:
            df = pd.read_csv(file_path, dtype=str, encoding="latin_1", sep=";")

        # Add columns to share data with the ASP.
        df = self.add_columns_for_asp(df)

        # Step 1: clean data
        self.logger.info("✨ STEP 1: clean data!")
        df = self.clean_df(df)

        # Users with invalid NIRS are stored but without a NIR.
        df, invalid_nirs_df = self.filter_invalid_nirs(df)
        self.logger.info(f"Invalid nirs: {len(invalid_nirs_df)}.")

        self.logger.info("🚮 STEP 2: remove rows!")
        if invalid_nirs_only:
            df = invalid_nirs_df

        df, to_be_imported_df = self.remove_ignored_rows(df)
        self.logger.info(
            f"Continuing with {len(to_be_imported_df)} rows left ({self.get_ratio(len(to_be_imported_df), len(df))} %)."
        )

        # Step 3: import data.
        self.logger.info("🔥 STEP 3: create job seekers, approvals and job applications.")
        df = self.import_data_into_itou(df=df, to_be_imported_df=to_be_imported_df)

        # Step 4: create a CSV file including comments to be shared with the ASP.
        df = df.drop(["nir_is_valid", "siret_validated_by_asp"], axis=1)  # Remove useless columns.

        self.log_to_csv("fichier_final", df)
        self.logger.info("📖 STEP 4: log final results.")
        self.logger.info("You can transfer this file to the ASP: /exports/import_ai_bilan.csv")

        self.logger.info("-" * 80)
        self.logger.info("👏 Good job!")
