import logging

import pandas as pd
import unidecode
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand
from tqdm import tqdm

from itou.approvals.models import Approval
from itou.users.models import User
from itou.utils.validators import validate_nir


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

    def nir_is_valid(self, nir):
        try:
            validate_nir(nir)
        except ValidationError:
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
            if row.pph_prenom != self.format_name(job_seeker.first_name):
                self.logger.debug(
                    f"Different first name: {row.pph_prenom} is not {self.format_name(job_seeker.first_name)}"
                )

            if row.pph_nom_usage != self.format_name(job_seeker.last_name):
                self.logger.debug(
                    f"Different last name: {row.pph_nom_usage} is not {self.format_name(job_seeker.last_name)}"
                )

            if row.pph_date_naissance.date() != job_seeker.birthdate:
                self.logger.debug(
                    f"Different birthdate: {row.pph_date_naissance.date()} is not {job_seeker.birthdate}"
                )

            if not self.dry_run:
                job_seeker.nir = row.ppn_numero_inscription
                updated_job_seekers.append(job_seeker)

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

        # Keep all duplicated rows.
        duplicated_nirs = df[nir_column.duplicated(keep=False)]
        unique_duplicated_nirs = duplicated_nirs.ppn_numero_inscription.unique()
        self.logger.info(f"{len(duplicated_nirs)} different PASS IAE for {len(unique_duplicated_nirs)} unique NIR.")
        self.logger.info(
            f"{round(len(duplicated_nirs) / len(unique_duplicated_nirs), 2)} different PASS IAE per NIR as average."
        )
        nir_duplicates_percent = round((len(duplicated_nirs) / total_rows) * 100, 2)
        self.logger.info(
            f"{nir_duplicates_percent}% cases of duplicated NIR (different PASS IAE delivered for the same person)."
        )

        # Add a new column to know whether it's a NIR duplicate or not.
        df["nir_is_duplicated"] = nir_column.duplicated(keep=False)

        # Add a new column to know whether it's a PASS IAE duplicate or not.
        df["pass_is_duplicated"] = pass_column.duplicated(keep=False)
        pass_is_duplicated_percent = round((len(df[df.pass_is_duplicated])) / total_rows, 2) * 100
        self.logger.info(f"{pass_is_duplicated_percent}% of duplicated PASS IAE.")

        # Invalid NIR
        df["nir_is_valid"] = nir_column.apply(self.nir_is_valid)
        invalid_nirs = df[~df.nir_is_valid]
        valid_nirs = df[df.nir_is_valid]
        self.logger.info(f"{len(invalid_nirs)} invalid NIR and {len(valid_nirs)} valid NIR.")
        invalid_nirs_percent = round((len(invalid_nirs) / len(valid_nirs)) * 100, 2)
        self.logger.info(f"{invalid_nirs_percent}% invalid NIRS.")

        # It's complicated!
        complicated_cases = df[~df.nir_is_valid | df.pass_is_duplicated | df.nir_is_duplicated]
        easy_cases = df[df.nir_is_valid & ~df.pass_is_duplicated & ~df.nir_is_duplicated]
        assert len(easy_cases) + len(complicated_cases) == total_rows
        self.logger.info(f"{len(easy_cases)} easy cases and {len(complicated_cases)} complicated_cases.")
        easy_vs_complicated_percent = round(len(complicated_cases) / len(easy_cases), 2) * 100
        self.logger.info(f"{easy_vs_complicated_percent}% of complicated_cases.")

        # Update easy cases
        self.update_easy_cases(easy_cases.sample(1))

        # Don't do nothing for complicated cases for the moment.
        self.logger.info("-" * 80)
        self.logger.info("Done.")
