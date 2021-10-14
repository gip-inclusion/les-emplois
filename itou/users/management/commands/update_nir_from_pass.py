# pylint: disable=W1203

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

    def check_if_different(self, kind, first_value, second_value):
        if first_value != second_value:
            self.logger.debug(f"Different {kind}: {first_value} is not {second_value}")
            return False
        return True

    def format_name(self, name):
        return unidecode.unidecode(name.upper())

    def update_easy_cases(self, easy_cases):
        pass_list = easy_cases.agr_numero_agrement.tolist()
        approvals_qs = Approval.objects.filter(number__in=pass_list).select_related("user").all()

        updated_job_seekers = []
        not_updated_job_seekers = []

        self.logger.debug("Starting to import easy cases!")
        pbar = tqdm(total=len(easy_cases))
        for _, row in easy_cases.iterrows():
            pbar.update(1)
            try:
                approval = approvals_qs.get(number=row.agr_numero_agrement)
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

        self.logger.info("-" * 80)
        self.logger.info(f"{len(updated_job_seekers)} updated job seekers.")
        self.logger.info(f"{len(not_updated_job_seekers)} rows not existing in database.")

    def handle(self, file_path, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.dry_run = dry_run
        self.logger.info("Starting. Good luck…")
        self.logger.info("-" * 80)

        df = pd.read_excel(file_path)
        total_rows = len(df)

        nir_column = df.ppn_numero_inscription
        pass_column = df.agr_numero_agrement

        # Duplicated NIR mean PASS IAE have been delivered for the same person.
        duplicated_nirs = df[nir_column.duplicated(keep=False)]
        unique_duplicated_nirs = duplicated_nirs[NIR_COL].unique()
        self.logger.info(f"{len(duplicated_nirs)} different PASS IAE for {len(unique_duplicated_nirs)} unique NIR.")
        self.logger.info(f"{self.get_ratio(len(duplicated_nirs), total_rows)}% cases of duplicated NIR.")
        self.logger.info(
            f"{round(len(duplicated_nirs) / len(unique_duplicated_nirs), 2)} different PASS IAE per NIR as average."
        )

        # Add a new column to know whether it's a NIR duplicate or not.
        df["nir_is_duplicated"] = nir_column.duplicated(keep=False)

        # Add a new column to know whether it's a PASS IAE duplicate or not.
        df["pass_is_duplicated"] = pass_column.duplicated(keep=False)
        self.logger.info(f"{self.get_ratio(len(df[df.pass_is_duplicated]), total_rows)}% of duplicated PASS IAE.")

        #  Add a new column to know whether the NIR is valid or not..
        df["nir_is_valid"] = df.apply(self.nir_is_valid, axis=1)
        invalid_nirs = df[~df.nir_is_valid]
        valid_nirs = df[df.nir_is_valid]
        self.logger.info(f"{len(invalid_nirs)} invalid NIR and {len(valid_nirs)} valid NIR.")
        self.logger.info(f"{self.get_ratio(len(invalid_nirs), len(valid_nirs))}% invalid NIRS.")

        # Complicated cases have an invalid NIR, or a duplicated PASS IAE or a duplicated NIR.
        # It's complicated!
        complicated_cases = df[~df.nir_is_valid | df.pass_is_duplicated | df.nir_is_duplicated]
        easy_cases = df[df.nir_is_valid & ~df.pass_is_duplicated & ~df.nir_is_duplicated]
        assert len(easy_cases) + len(complicated_cases) == total_rows
        self.logger.info(f"{len(easy_cases)} easy cases and {len(complicated_cases)} complicated_cases.")
        self.logger.info(f"{self.get_ratio(len(complicated_cases), len(easy_cases))}% of complicated_cases.")

        # Update easy cases
        self.update_easy_cases(easy_cases.sample(100))

        # Ignore complicated cases for the moment.
        self.logger.info("-" * 80)
        self.logger.info("Done.")
