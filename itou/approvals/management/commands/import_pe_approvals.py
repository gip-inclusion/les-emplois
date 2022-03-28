import datetime

import pandas as pd
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.approvals.models import PoleEmploiApproval
from itou.utils.management_commands import DeprecatedLoggerMixin


FLUSH_SIZE = 5000

# Sometimes, there are multiple date formats in the XLS file.
# Otherwise it would be too easy.
DATE_FORMAT = "%m/%d/%Y"
DATE_FORMAT2 = "%d/%m/%y"
DATE_FORMAT3 = "%d%b%Y"
FALLBACK_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_date(value):
    value = str(value).strip()
    try:
        return datetime.datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(value, DATE_FORMAT2).date()
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(value, DATE_FORMAT3).date()
    except ValueError:
        pass
    return datetime.datetime.strptime(value, FALLBACK_DATE_FORMAT).date()


def parse_str(src, max_len):
    if not isinstance(src, str):
        return src, "instance"
    s = src.strip().replace(" ", "")
    if len(s) > max_len:
        return s, "length"
    return s, None


def load_and_sort(file_path):
    df = pd.read_excel(file_path)
    df["DATE_DEB"] = pd.to_datetime(df.DATE_DEB, format=DATE_FORMAT)
    df.sort_values("DATE_DEB")
    return df


class Command(DeprecatedLoggerMixin, BaseCommand):
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
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    def handle(self, file_path, wet_run=False, **options):
        self.set_logger(options.get("verbosity"))
        now = timezone.now().date()

        count_before = PoleEmploiApproval.objects.count()
        count_errors = 0
        count_invalid_agr_dec = 0
        count_canceled_approvals = 0
        count_success = 0
        unique_approval_suffixes = {}

        df = load_and_sort(file_path)
        self.stdout.write(f"Ready to import up to length={len(df)} approvals from file={file_path}")

        bulk_create_queue = []
        for idx, row in df.iterrows():
            CODE_STRUCT_AFFECT_BENE = str(row["CODE_STRUCT_AFFECT_BENE"])
            if len(CODE_STRUCT_AFFECT_BENE) not in [4, 5]:
                self.stderr.write(f"! wrong CODE_STRUCT_AFFECT_BENE={CODE_STRUCT_AFFECT_BENE}, skipping...")
                count_errors += 1
                continue

            # This is known as "Identifiant Pôle emploi".
            ID_REGIONAL_BENE = str(row["ID_REGIONAL_BENE"]).strip()
            if len(ID_REGIONAL_BENE) < 8:
                self.stderr.write(f"! bad length for ID_REGIONAL_BENE={ID_REGIONAL_BENE} (PE ID) found, skipping…")
                count_errors += 1
                continue

            # Check the format of ID_REGIONAL_BENE.
            # First 7 chars should be digits, last char should be alphanumeric.
            if not ID_REGIONAL_BENE[:7].isdigit() or not ID_REGIONAL_BENE[7:].isalnum():
                self.stderr.write(f"! bad format for ID_REGIONAL_BENE={ID_REGIONAL_BENE} (PE ID) found, skipping…")
                count_errors += 1
                continue

            NOM_USAGE_BENE, err = parse_str(row["NOM_USAGE_BENE"], 29)
            if err:
                self.stderr.write(f"! unable to parse NOM_USAGE_BENE={NOM_USAGE_BENE} err={err}, skipping…")
                count_errors += 1
                continue

            PRENOM_BENE, err = parse_str(row["PRENOM_BENE"], 13)
            if err:
                self.stderr.write(f"! unable to parse PRENOM_BENE={PRENOM_BENE} err={err}, skipping…")
                count_errors += 1
                continue

            NOM_NAISS_BENE, err = parse_str(row["NOM_NAISS_BENE"], 25)
            if err:
                self.stderr.write(f"! unable to parse NOM_NAISS_BENE={NOM_NAISS_BENE} err={err}, skipping…")
                count_errors += 1
                continue

            NUM_AGR_DEC = str(row["NUM_AGR_DEC"]).strip().replace(" ", "")
            if len(NUM_AGR_DEC) not in [12, 15]:
                self.stderr.write(f"! invalid NUM_AGR_DEC={NUM_AGR_DEC} len={len(NUM_AGR_DEC)}, skipping…")
                count_invalid_agr_dec += 1
                continue

            # Keep track of unique suffixes added by PE at the end of a 12 chars number
            # that increases the length to 15 chars.
            if len(NUM_AGR_DEC) > 12:
                suffix = NUM_AGR_DEC[12:]
                unique_approval_suffixes[suffix] = unique_approval_suffixes.get(suffix, 0) + 1

            DATE_DEB_AGR_DEC = parse_date(row["DATE_DEB"])
            DATE_FIN_AGR_DEC = parse_date(row["DATE_FIN"])
            DATE_NAISS_BENE = parse_date(row["DATE_NAISS_BENE"])

            # Same start and end dates means that the approval has been canceled.
            if DATE_DEB_AGR_DEC == DATE_FIN_AGR_DEC:
                self.stderr.write(
                    f"> canceled approval found AGR_DEC={NUM_AGR_DEC} "
                    f"NOM={NOM_USAGE_BENE} PRENOM={PRENOM_BENE}, skipping..."
                )
                count_canceled_approvals += 1
                continue

            # Pôle emploi sends us the year in a two-digit format ("14/03/68")
            # but strptime() will set it in the future:
            # >>> datetime.datetime.strptime("14/03/68", "%d/%m/%y").date()
            # datetime.date(2068, 3, 14)
            if DATE_NAISS_BENE.year > now.year:
                str_d = DATE_NAISS_BENE.strftime("%Y-%m-%d")
                # Replace the first 2 digits by "19".
                str_d = f"19{str_d[2:]}"
                DATE_NAISS_BENE = datetime.datetime.strptime(str_d, "%Y-%m-%d")

            count_success += 1
            if wet_run:
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
                if len(bulk_create_queue) > FLUSH_SIZE:
                    # Setting the ignore_conflicts parameter to True tells the
                    # database to ignore failure to insert any rows that fail
                    # constraints such as duplicate unique values.
                    # This allows us to update the database when a new source
                    # file is available.
                    PoleEmploiApproval.objects.bulk_create(bulk_create_queue, ignore_conflicts=True)
                    bulk_create_queue = []

        # Create any remaining objects.
        if wet_run and bulk_create_queue:
            PoleEmploiApproval.objects.bulk_create(bulk_create_queue, ignore_conflicts=True)

        count_after = PoleEmploiApproval.objects.count()

        self.stdout.write("PEApprovals import summary:")
        self.stdout.write(f"  Number of approvals, before    : {count_before}")
        self.stdout.write(f"  Number of approvals, after     : {count_after}")
        self.stdout.write(f"  Added approvals                : {count_after - count_before}")
        self.stdout.write(f"  Sucessfully parsed lines       : {count_success}")
        self.stdout.write(f"  Unexpected parsing errors      : {count_errors}")
        self.stdout.write(f"  Invalid approval number errors : {count_invalid_agr_dec}")
        self.stdout.write(f"  Canceled approvals             : {count_canceled_approvals}")
        self.stdout.write("Done.")
