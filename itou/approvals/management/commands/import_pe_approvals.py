import datetime
import logging
import os

import pandas as pd
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.approvals.models import PoleEmploiApproval


class Command(BaseCommand):
    """
    Import Pole emploi's approvals (or `agrément` in French) into the database.

    To debug:
        django-admin import_pe_approvals --file-path=/tmp/2020_02_12_base_agrements_aura.xlsx --dry-run
        django-admin import_pe_approvals --file-path=/tmp/2020_02_12_base_agrements_aura.xlsx --dry-run --verbosity=2

    To populate the database:
        django-admin import_pe_approvals --file-path=/tmp/2020_02_12_base_agrements_aura.xlsx
    """

    help = "Import the content of the Pole emploi's approvals xlsx file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the XLSX file to import",
        )
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to import")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def handle(self, file_path, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        now = timezone.now().date()
        DATE_FORMAT = "%d/%m/%y"

        count_before = PoleEmploiApproval.objects.count()
        count_canceled_approvals = 0
        unique_approval_suffixes = {}

        file_size_in_bytes = os.path.getsize(file_path)
        self.stdout.write(f"Opening a {file_size_in_bytes >> 20} MB file… (this will take some time)")

        bulk_create_queue = []
        chunk_size = 5000

        df = pd.read_excel(file_path)
        df["DATE_HISTO"] = pd.to_datetime(df.DATE_HISTO, format=DATE_FORMAT)
        df.sort_values("DATE_HISTO")
        first_approval_date = df.iloc[0].DATE_HISTO.strftime(DATE_FORMAT)
        last_approval_date = df.iloc[-1].DATE_HISTO.strftime(DATE_FORMAT)

        df["DATE_DEB"] = pd.to_datetime(df.DATE_DEB, format=DATE_FORMAT)
        df["DATE_FIN"] = pd.to_datetime(df.DATE_FIN, format=DATE_FORMAT)
        df["DATE_NAISS_BENE"] = pd.to_datetime(df.DATE_NAISS_BENE, format=DATE_FORMAT)

        self.stdout.write("Ready.")
        self.stdout.write(f"Importing approvals from {first_approval_date} to {last_approval_date}")
        self.stdout.write("Creating approvals… 0%")

        last_progress = 0
        for idx, row in df.iterrows():

            if idx == 0:
                # Skip XLSX header.
                continue

            progress = int((100 * idx) / len(df))
            if progress > last_progress + 5:
                self.stdout.write(f"Creating approvals… {progress}%")
                last_progress = progress

            CODE_STRUCT_AFFECT_BENE = str(row["CODE_STRUCT_AFFECT_BENE"])
            assert len(CODE_STRUCT_AFFECT_BENE) in [4, 5]

            # This is known as "Identifiant Pôle emploi".
            ID_REGIONAL_BENE = row["ID_REGIONAL_BENE"].strip()
            assert len(ID_REGIONAL_BENE) == 8
            # Check the format of ID_REGIONAL_BENE.
            # First 7 chars should be digits.
            assert ID_REGIONAL_BENE[:7].isdigit()
            # Last char should be alphanumeric.
            assert ID_REGIONAL_BENE[7:].isalnum()

            NOM_USAGE_BENE = row["NOM_USAGE_BENE"].strip()
            assert "  " not in NOM_USAGE_BENE
            # max length 29

            PRENOM_BENE = row["PRENOM_BENE"].strip()
            assert "  " not in PRENOM_BENE
            # max length 13

            NOM_NAISS_BENE = row["NOM_NAISS_BENE"].strip()
            assert "  " not in NOM_NAISS_BENE
            # max length 25

            NUM_AGR_DEC = row["NUM_AGR_DEC"].strip().replace(" ", "")
            assert " " not in NUM_AGR_DEC
            if len(NUM_AGR_DEC) not in [12, 15]:
                self.stderr.write("-" * 80)
                self.stderr.write("Invalid number, skipping…")
                self.stderr.write(CODE_STRUCT_AFFECT_BENE)
                self.stderr.write(ID_REGIONAL_BENE)
                self.stderr.write(NOM_USAGE_BENE)
                self.stderr.write(PRENOM_BENE)
                self.stderr.write(NOM_NAISS_BENE)
                self.stderr.write(NUM_AGR_DEC)
                continue

            # Keep track of unique suffixes added by PE at the end of a 12 chars number
            # that increases the length to 15 chars.
            if len(NUM_AGR_DEC) > 12:
                suffix = NUM_AGR_DEC[12:]
                unique_approval_suffixes[suffix] = unique_approval_suffixes.get(suffix, 0) + 1

            DATE_DEB_AGR_DEC = row["DATE_DEB"]
            DATE_FIN_AGR_DEC = row["DATE_FIN"]

            # Same start and end dates means that the approval has been canceled.
            if DATE_DEB_AGR_DEC == DATE_FIN_AGR_DEC:
                count_canceled_approvals += 1
                self.logger.debug("-" * 80)
                self.logger.debug("Canceled approval found, skipping…")
                self.logger.debug("%s - %s - %s", NUM_AGR_DEC, NOM_USAGE_BENE, PRENOM_BENE)
                continue

            DATE_NAISS_BENE = row["DATE_NAISS_BENE"]

            # Pôle emploi sends us the year in a two-digit format ("14/03/68")
            # but strptime() will set it in the future:
            # >>> datetime.datetime.strptime("14/03/68", "%d/%m/%y").date()
            # datetime.date(2068, 3, 14)
            if DATE_NAISS_BENE.year > now.year:
                str_d = DATE_NAISS_BENE.strftime("%Y-%m-%d")
                # Replace the first 2 digits by "19".
                str_d = f"19{str_d[2:]}"
                DATE_NAISS_BENE = datetime.datetime.strptime(str_d, "%Y-%m-%d")

            if not dry_run:
                pe_approval = PoleEmploiApproval()
                pe_approval.pe_structure_code = CODE_STRUCT_AFFECT_BENE
                pe_approval.pole_emploi_id = ID_REGIONAL_BENE
                pe_approval.number = NUM_AGR_DEC
                pe_approval.first_name = PRENOM_BENE
                pe_approval.last_name = NOM_USAGE_BENE
                pe_approval.birth_name = NOM_NAISS_BENE
                pe_approval.birthdate = DATE_NAISS_BENE
                pe_approval.start_at = DATE_DEB_AGR_DEC
                pe_approval.end_at = DATE_FIN_AGR_DEC
                bulk_create_queue.append(pe_approval)
                if len(bulk_create_queue) > chunk_size:
                    # Setting the ignore_conflicts parameter to True tells the
                    # database to ignore failure to insert any rows that fail
                    # constraints such as duplicate unique values.
                    # This allows us to update the database when a new source
                    # file is available.
                    PoleEmploiApproval.objects.bulk_create(bulk_create_queue, ignore_conflicts=True)
                    bulk_create_queue = []

        # Create any remaining objects.
        if not dry_run and bulk_create_queue:
            PoleEmploiApproval.objects.bulk_create(bulk_create_queue, ignore_conflicts=True)

        count_after = PoleEmploiApproval.objects.count()

        self.stdout.write("-" * 80)
        self.stdout.write(f"Before: {count_before}")
        self.stdout.write(f"After: {count_after}")
        self.stdout.write(f"New ojects: {count_after - count_before}")
        self.stdout.write(f"Skipped {count_canceled_approvals} canceled approvals")
        self.stdout.write(f"Unique suffixes: {unique_approval_suffixes}")
        self.stdout.write("Done.")
