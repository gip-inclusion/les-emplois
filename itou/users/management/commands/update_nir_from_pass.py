# flake8: noqa
# pylint: disable=[W1203, C0121]

import datetime
import logging
import re

import pandas as pd
import unidecode
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand
from tqdm import tqdm

from itou.approvals.models import Approval
from itou.users.models import User
from itou.utils.validators import validate_nir


BIRTHDATE_COL = "pph_date_naissance"
FIRST_NAME_COL = "pph_prenom"
LAST_NAME_COL = "pph_nom_usage"
NIR_COL = "ppn_numero_inscription"
PASS_COL = "agr_numero_agrement"


class Command(BaseCommand):
    """
    Deduplicate job seekers.

    This is temporary and should be deleted after the release of the NIR
    which should prevent duplication.

    To run the command without any change in DB and have a preview of which
    accounts will be merged:
        django-admin deduplicate_job_seekers --dry-run

    To merge duplicates job seekers in the database:
        django-admin deduplicate_job_seekers
    """

    help = "Deduplicate job seekers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="")
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the XLSX file to import",
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
        approval = row[PASS_COL]
        wrong_approval_numbers = ["999990000000", "999999999999", "999999000000"]
        return len(approval) == 12 and approval.startswith("99999") and approval not in wrong_approval_numbers

    def check_if_different(self, kind, first_value, second_value):
        if first_value != second_value:
            self.logger.debug(f"Different {kind}: {first_value} is not {second_value}")
            return False
        return True

    def format_name(self, name):
        return unidecode.unidecode(name.upper())

    def update_job_seekers(self, df):
        approval_list = df[PASS_COL].tolist()
        approvals_qs = Approval.objects.filter(number__in=approval_list).select_related("user").all()

        updated_job_seekers = []
        not_updated_job_seekers = []

        pbar = tqdm(total=len(df))
        for _, row in df.iterrows():
            pbar.update(1)
            try:
                approval = approvals_qs.get(number=row[PASS_COL])
            except ObjectDoesNotExist:
                not_updated_job_seekers.append(row)
                continue

            job_seeker = approval.user
            self.check_if_different("first name", row[FIRST_NAME_COL], self.format_name(job_seeker.first_name))
            self.check_if_different("last_name", row[LAST_NAME_COL], self.format_name(job_seeker.last_name))

            assert isinstance(row[BIRTHDATE_COL], datetime.datetime)
            self.check_if_different("birthdate", row[BIRTHDATE_COL].date(), job_seeker.birthdate)

            if not self.dry_run:
                job_seeker.nir = row[NIR_COL]
                updated_job_seekers.append(job_seeker)

        if not self.dry_run:
            User.objects.bulk_update(updated_job_seekers, ["nir"])

        self.logger.info(f"{len(updated_job_seekers)} updated job seekers.")
        self.logger.info(f"{len(not_updated_job_seekers)} rows not existing in database.")
        logs = [f"| PASS : {u[PASS_COL]}, NIR : {u[NIR_COL]} |" for u in not_updated_job_seekers]
        self.logger.info(logs)

    def clean_and_merge_duplicated_approval(self, df):
        df = df.copy()
        df.is_treated = True

        # Same birthdate, NIR and PASS.
        # Don't mark them as treated to keep them integrated to complicated cases.
        complicated_cases = df[~df.duplicated(subset=[PASS_COL, NIR_COL, BIRTHDATE_COL], keep=False)]
        df.loc[complicated_cases.index, "is_treated"] = False

        # Merge kept rows.
        kept_rows = df[df.duplicated(subset=[PASS_COL, NIR_COL, BIRTHDATE_COL], keep="first")]
        df.loc[kept_rows.index, "approval_is_duplicated"] = False
        df.loc[kept_rows.index, "nir_is_duplicated"] = False
        self.logger.info(
            f"{len(complicated_cases)} don't have the same birthdate, NIR and PASS. Continuing with "
            f"{len(kept_rows)} merged unique rows."
        )

        return df

    def handle(self, file_path, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.dry_run = dry_run
        self.logger.info("Starting. Good luck…")
        self.logger.info("-" * 80)

        df = pd.read_excel(file_path).sample(2000)
        total_rows = len(df)
        # Add a new column to mark rows as treated. Store only treated data.
        df["is_treated"] = False

        # Step 1: clean data
        self.logger.info("✨ STEP 1: clean!")
        df[NIR_COL] = df[NIR_COL].apply(str)
        df[PASS_COL] = df[PASS_COL].apply(str)

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
        self.logger.info(f"Leaving {len(invalid_rows)} rows behind")

        # Remove treated rows.
        df = df[~df.is_treated].copy()

        self.logger.info(f"🎯 STEP 2: hunt duplicates! {len(df)} rows left.")

        # Step 2: treat duplicates.
        # Duplicated NIR mean PASS IAE have been delivered for the same person.
        # Add a new column to know whether it's a NIR duplicate or not.
        df["nir_is_duplicated"] = df[NIR_COL].duplicated(keep=False)

        # Add a new column to know whether it's a PASS IAE duplicate or not.
        df["approval_is_duplicated"] = df[PASS_COL].duplicated(keep=False)
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
            self.logger.info("Duplicated NIRs:")
            self.logger.info(duplicated_nirs)

        # Mark easy cases as treated automatically:
        # PASS number and NIR numbers are unique.
        easy_cases = df[(df.approval_is_duplicated == False) & (df.nir_is_duplicated == False)]
        df.loc[easy_cases.index, "is_treated"] = True

        # Step 3: update job seekers.
        self.logger.info(f"🔥 STEP 3: update job seekers. {len(easy_cases)} rows left.")
        self.update_job_seekers(easy_cases)

        # Step 4: recap!
        self.logger.info(f"💪 STEP 4: list what's left.")

        # Complicated cases have an invalid NIR or a duplicated NIR.
        # They also include PASS IAE duplicates impossible to merge automatically.
        # Ignore untreated cases for the moment.
        treated_cases = df[df.is_treated]
        untreated_cases = df[df.is_treated == False]  # Using ~ would return an error if no result found.
        self.logger.info(f"{len(treated_cases)} treated cases and {len(untreated_cases)} complicated cases.")
        self.logger.info(f"{self.get_ratio(len(untreated_cases), len(treated_cases))}% of complicated cases.")
        if not untreated_cases.empty:
            self.logger.info(f"Complicated cases to handle manually:")
            self.logger.info(untreated_cases)

        self.logger.info("-" * 80)
        self.logger.info("👏 Good job!")
