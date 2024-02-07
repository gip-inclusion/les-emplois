# flake8: noqa

import csv
import datetime
import re
from pathlib import Path

import pandas as pd
import unidecode
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from itou.utils.command import BaseCommand
from tqdm import tqdm

from itou.approvals.models import Approval
from itou.utils.management_commands import DeprecatedLoggerMixin
from itou.utils.validators import validate_nir


BIRTHDATE_COL = "pph_date_naissance"
FIRST_NAME_COL = "pph_prenom"
LAST_NAME_COL = "pph_nom_usage"
NIR_COL = "ppn_numero_inscription"
APPROVAL_COL = "agr_numero_agrement"


class Command(DeprecatedLoggerMixin, BaseCommand):
    """
    Update job seekers' account with their NIR (social security number) if an approval has been issued.

    To do so, parse an Excel file containing job seekers' birthdate, approval number and NIR.

    To run the command without any change in DB and have a preview of the results:
        django-admin update_nir_from_pass --file-path=path/to/file.xlsx --dry-run

    To disable debug logs (not matching birthdate, first name or last name between file and DB):
        django-admin update_nir_from_pass --file-path=path/to/file.xlsx --verbosity=0

    To work with a sample rather than with the whole file:
        django-admin update_nir_from_pass --file-path=path/to/file.xlsx --sample-size=2000

    To update job seekers in the database:
        django-admin update_nir_from_pass --file-path=path/to/file.xlsx
    """

    help = "Update NIR from PASS"

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
            help="Absolute path of the XLSX file to import",
        )

    def get_ratio(self, first_value, second_value):
        return round((first_value / second_value) * 100, 2)

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

    def nir_is_valid(self, row):
        nir = row[NIR_COL]
        birthdate = row[BIRTHDATE_COL]
        if not isinstance(birthdate, datetime.datetime):
            self.logger.debug(f"BIRTHDATE IS NOT A DATETIME! {birthdate} {type(birthdate)}")
        try:
            validate_nir(nir)
            nir_regex = r"^[12]([0-9]{2})([0-1][0-9])*."
            match = re.match(nir_regex, nir)
            is_valid = match.group(1) == birthdate.strftime("%y") and match.group(2) == birthdate.strftime("%m")
            if not is_valid:
                raise ValidationError("Ce numéro n'est pas valide.")
        except ValidationError:
            return False
        return True

    def approval_is_valid(self, row):
        approval = row[APPROVAL_COL]
        wrong_approval_numbers = ["999990000000", "999999999999", "999999000000", "999992100000"]
        # settings.ASP.ASP_ITOU_PREFIX is XXXXX in local.
        return len(approval) == 12 and approval.startswith("99999") and approval not in wrong_approval_numbers

    def format_name(self, name):
        return unidecode.unidecode(name.upper())

    def update_job_seekers(self, df):
        nb_updated_job_seekers = 0
        not_updated_job_seekers = []
        not_same_personal_info = []
        not_same_personal_info_dict = {
            "Prénom plateforme": None,
            "Prénom ASP": None,
            "Nom plateforme": None,
            "Nom ASP": None,
            "Date de naissance plateforme": None,
            "Date de naissance ASP": None,
            "PASS IAE": None,
            "NIR": None,
        }

        pbar = tqdm(total=len(df))
        for _, row in df.iterrows():
            pbar.update(1)
            try:
                approval = Approval.objects.get(number=row[APPROVAL_COL])
            except ObjectDoesNotExist:
                not_updated_job_seekers.append(row.to_dict())
                continue

            job_seeker = approval.user
            if row[FIRST_NAME_COL] != self.format_name(job_seeker.first_name):
                not_same_personal_info.append(
                    not_same_personal_info_dict
                    | {
                        "Prénom plateforme": self.format_name(job_seeker.first_name),
                        "Prénom ASP": row[FIRST_NAME_COL],
                        "PASS IAE": row[APPROVAL_COL],
                        "NIR": row[NIR_COL],
                    }
                )
                continue

            if row[LAST_NAME_COL] != self.format_name(job_seeker.last_name):
                not_same_personal_info.append(
                    not_same_personal_info_dict
                    | {
                        "Nom plateforme": self.format_name(job_seeker.last_name),
                        "Nom ASP": row[LAST_NAME_COL],
                        "PASS IAE": row[APPROVAL_COL],
                        "NIR": row[NIR_COL],
                    }
                )
                continue

            assert isinstance(row[BIRTHDATE_COL], datetime.datetime)

            if row[BIRTHDATE_COL].date() != job_seeker.birthdate:
                not_same_personal_info.append(
                    not_same_personal_info_dict
                    | {
                        "Date de naissance plateforme": job_seeker.birthdate,
                        "Date de naissance ASP": row[BIRTHDATE_COL].date(),
                        "PASS IAE": row[APPROVAL_COL],
                        "NIR": row[NIR_COL],
                    }
                )
                continue

            if not self.dry_run:
                job_seeker.jobseeker_profile.nir = row[NIR_COL]
                if job_seeker.jobseeker_profile.nir:
                    job_seeker.jobseeker_profile.lack_of_nir_reason = ""
                nb_updated_job_seekers += 1

            if not self.dry_run:
                job_seeker.jobseeker_profile.save()

        self.logger.info(f"{nb_updated_job_seekers} updated job seeker profiles.")
        self.logger.info(f"{len(not_updated_job_seekers)} rows not existing in database.")
        self.log_to_csv(csv_name="inexistent_users", logs=not_updated_job_seekers)
        self.logger.info(f"Inexistent users exported to {settings.EXPORT_DIR}/inexistent_users.csv.")
        self.log_to_csv(csv_name="not_matching_personal_infos", logs=not_same_personal_info)
        self.logger.info(
            f"Users with inconsistent data exported to {settings.EXPORT_DIR}/not_matching_personal_infos.csv."
        )

    def clean_and_merge_duplicated_approval(self, df):
        df = df.copy()
        df.is_treated = True

        # Merge duplicated PASS. Caution: Duplicated NIRS may still be present at the end.
        kept_rows = df[df.duplicated(subset=[APPROVAL_COL, NIR_COL, BIRTHDATE_COL], keep="first")]
        df.loc[kept_rows.index, "approval_is_duplicated"] = False
        df.loc[kept_rows.index, "nir_is_duplicated"] = False

        # Same birthdate, NIR and PASS.
        # Don't mark them as treated to keep them integrated to complicated cases.
        complicated_cases = kept_rows[~kept_rows.duplicated(subset=[APPROVAL_COL, NIR_COL, BIRTHDATE_COL], keep=False)]
        df.loc[complicated_cases.index, "is_treated"] = False
        df.loc[complicated_cases.index, "approval_is_duplicated"] = True
        df.loc[complicated_cases.index, "nir_is_duplicated"] = True

        kept_rows_count = len(df[df.is_treated & (df.approval_is_duplicated == False)])

        self.logger.info(
            f"{len(complicated_cases)} don't have the same birthdate, NIR and PASS. Continuing with "
            f"{kept_rows_count} merged unique rows."
        )
        return df

    def handle(self, file_path, *, dry_run, **options):
        self.dry_run = dry_run
        self.set_logger(options.get("verbosity"))
        sample_size = options.get("sample_size")

        self.logger.info("Starting. Good luck…")
        self.logger.info("-" * 80)

        if sample_size:
            df = pd.read_excel(file_path).sample(int(sample_size))
        else:
            df = pd.read_excel(file_path)

        total_rows = len(df)
        # Add a new column to mark rows as treated. Store only treated data.
        df["is_treated"] = False

        # Step 1: clean data
        self.logger.info("✨ STEP 1: clean!")
        df[NIR_COL] = df[NIR_COL].apply(str)
        df[APPROVAL_COL] = df[APPROVAL_COL].apply(str)

        # Add a new column to know whether the approval is valid or not.
        # If an approval is not valid, its number is replaced by "nan".
        df["approval_is_valid"] = df.apply(self.approval_is_valid, axis=1)
        invalid_approvals = df[~df.approval_is_valid]
        valid_approvals = df[df.approval_is_valid]
        self.logger.info(f"{len(invalid_approvals)} invalid approvals and {len(valid_approvals)} valid approvals.")
        self.logger.info(f"{self.get_ratio(len(invalid_approvals), len(valid_approvals))}% of invalid approvals.")

        # Add a new column to know whether the NIR is valid or not.
        # If a NIR is not valid, its number is replaced by "nan".
        df["nir_is_valid"] = df.apply(self.nir_is_valid, axis=1)
        invalid_nirs = df[~df.nir_is_valid]
        valid_nirs = df[df.nir_is_valid]
        self.logger.info(f"{len(invalid_nirs)} invalid NIR and {len(valid_nirs)} valid NIR.")
        self.logger.info(f"{self.get_ratio(len(invalid_nirs), len(valid_nirs))}% of invalid NIRS.")

        # Mark invalid NIRs or approvals as treated rows.
        df.loc[invalid_nirs.index, "is_treated"] = True
        df.loc[invalid_approvals.index, "is_treated"] = True

        invalid_rows = df[~df.nir_is_valid | ~df.approval_is_valid]
        self.logger.info(
            f"Leaving {len(invalid_rows)} rows behind ({self.get_ratio(len(invalid_rows), total_rows)}%)."
        )

        # Remove treated rows to continue with valid NIRs and approvals.
        df = df.drop(df[df.is_treated].index)
        self.logger.info(f"Continuing with {len(df)} rows left.")

        self.logger.info(f"🎯 STEP 2: hunt duplicates!")

        # Step 2: treat duplicates.
        # Duplicated NIR means PASS IAE have been delivered for the same person.
        # Add a new column to know whether it's a NIR duplicate or not.
        df["nir_is_duplicated"] = df[NIR_COL].duplicated(keep=False)

        # Add a new column to know whether it's a PASS IAE duplicate or not.
        df["approval_is_duplicated"] = df[APPROVAL_COL].duplicated(keep=False)
        # Then remove wrong PAsS IAE numbers, merge duplicates and mark complicated cases as untreated.
        result_df = self.clean_and_merge_duplicated_approval(df[df["approval_is_duplicated"]])
        df.update(result_df)
        self.logger.info(f"{self.get_ratio(len(df[df.approval_is_duplicated]), total_rows)}% of duplicated PASS IAE.")

        duplicated_nirs = df[df.nir_is_duplicated & df.nir_is_valid & (df.is_treated == False)]
        if not duplicated_nirs.empty:
            unique_duplicated_nirs = duplicated_nirs[NIR_COL].unique()
            self.logger.info(
                f"{len(duplicated_nirs)} different PASS IAE for {len(unique_duplicated_nirs)} unique NIR."
            )
            self.logger.info(f"{self.get_ratio(len(duplicated_nirs), total_rows)}% cases of duplicated NIRs.")
            self.logger.info(
                f"{round(len(duplicated_nirs) / len(unique_duplicated_nirs), 2)} different PASS IAE per NIR as average."
            )

        # Mark easy cases as treated automatically:
        # PASS number and NIR numbers are unique.
        easy_cases = df[(df.approval_is_duplicated == False) & (df.nir_is_duplicated == False)]
        df.loc[easy_cases.index, "is_treated"] = True

        # Step 3: update job seekers.
        self.logger.info(f"🔥 STEP 3: update job seekers.")
        self.update_job_seekers(easy_cases)

        # Step 4: recap!
        self.logger.info(f"💪 STEP 4: list what's left.")

        # Complicated cases have an invalid NIR or a duplicated NIR.
        # They also include PASS IAE duplicates impossible to merge automatically.
        # Ignore untreated cases for the moment.
        treated_cases = df[df.is_treated]
        untreated_cases = df[df.is_treated == False]  # Using ~ would return an error if no result found.
        self.logger.info(
            f"{len(treated_cases)} treated cases and {len(untreated_cases)} complicated cases (without wrong NIRs and approvals)."
        )
        self.logger.info(f"{self.get_ratio(len(untreated_cases), len(treated_cases))}% of complicated cases.")
        self.logger.info(
            f"{self.get_ratio(len(treated_cases), total_rows)}% of treated cases totally (with wrong NIRs and approvals)."
        )
        if not untreated_cases.empty:
            self.logger.debug(f"Complicated cases to handle manually:")
            self.logger.debug(untreated_cases)
            self.log_to_csv(csv_name="complicated_cases", logs=untreated_cases)
            self.logger.info(f"Complicated cases exported to {settings.EXPORT_DIR}/complicated_cases.csv.")

        self.logger.info("-" * 80)
        self.logger.info("👏 Good job!")
