import argparse
import io
import zipfile

import pandas as pd
from django.conf import settings
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.cities.models import City
from itou.common_apps.address.departments import department_from_postcode
from itou.companies.enums import CompanyKind
from itou.companies.management.commands._import_siae.utils import (
    geocode_siae,
    remap_columns,
    sync_structures,
)
from itou.companies.models import Company
from itou.utils import asp as asp_utils
from itou.utils.asp import REMOTE_DOWNLOAD_DIR
from itou.utils.command import BaseCommand
from itou.utils.date import monday_of_the_week


class FileOfTheWeekNotFound(Exception):
    pass


def build_ea_eatt(row):
    company = Company()
    company.siret = row.siret
    company.kind = row.kind
    assert company.kind in [CompanyKind.EA, CompanyKind.EATT]
    company.source = Company.SOURCE_EA_EATT

    company.name = row["name"]  # row.name returns row index.
    assert not company.name.isnumeric()

    company.email = ""  # Do not make the authentification email public!
    company.auth_email = row.auth_email
    company.address_line_1 = row.address_line_1
    company.address_line_2 = row.address_line_2
    company.post_code = row.post_code
    if row.insee_city:
        company.insee_city = row.insee_city
        company.city = company.insee_city.name
        company.department = company.insee_city.department
    else:
        company.department = department_from_postcode(company.post_code)

    geocode_siae(company)
    return company


class Command(BaseCommand):
    """
    Import EA and EATT data into the database using the "flux EA2"

    EA = "Entreprise adaptée".
    EATT = "Entreprise adaptée de travail temporaire".
    """

    ATOMIC_HANDLE = True

    help = 'Import EA and EATT data into the database using the "flux EA2"'

    NUMBER_OF_ARCHIVES_TO_KEEP = 3

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--from-archive", dest="from_archive", type=argparse.FileType(mode="rb"), help="The ZIP file"
        )
        group.add_argument("--from-asp", dest="from_asp", action="store_true")

        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def retrieve_archive_of_the_week(self):
        FILENAME_PREFIX = "FLUX_EA2_ITOU_"

        with asp_utils.get_sftp_connection() as sftp:
            self.logger.info('Connected to "%s" as "%s"', settings.ASP_SFTP_HOST, settings.ASP_SFTP_USER)
            self.logger.info('Current remote dir is "%s"', sftp.normalize("."))
            sftp.chdir(REMOTE_DOWNLOAD_DIR)  # Get into the download folder

            monday = monday_of_the_week().strftime("%Y%m%d")
            files_of_the_week = [
                filename
                for filename in sftp.listdir()
                if filename.startswith(FILENAME_PREFIX) and filename > f"{FILENAME_PREFIX}{monday}"
            ]
            self.logger.info("Files matching for this week '%s': %s", monday, ", ".join(files_of_the_week))
            if not files_of_the_week:
                raise FileOfTheWeekNotFound()
            if len(files_of_the_week) > 1:
                raise RuntimeError(f"Too many files for this week: {files_of_the_week}")

            archive_of_the_week = files_of_the_week[0]
            self.logger.info("Found the archive_of_the_week: '%s'", archive_of_the_week)
            archive = io.BytesIO()
            sftp.getfo(archive_of_the_week, archive)
            return archive

    def clean_old_archives(self, *, wet_run):
        with asp_utils.get_sftp_connection() as sftp:
            self.logger.info('Connected to "%s" as "%s"', settings.ASP_SFTP_HOST, settings.ASP_SFTP_USER)
            self.logger.info('Current remote dir is "%s"', sftp.normalize("."))

            sftp.chdir(REMOTE_DOWNLOAD_DIR)  # Get into the download folder
            filenames = list(sorted(sftp.listdir(), reverse=True))
            for filename in filenames[max(self.NUMBER_OF_ARCHIVES_TO_KEEP, 0) :]:
                self.logger.info("Going to delete the old archive '%s'", filename)
                if wet_run:
                    sftp.remove(filename)
                    self.logger.info("Old archive '%s' was deleted", filename)

    def process_file(self, file, *, wet_run=False):
        header = next(file)
        if not header.startswith("L|ASP|EA|"):  # Start of file header
            raise RuntimeError("File doesn't conform to the expected format: %s", "L|ASP|EA|")

        columns = next(file).rstrip("\n|").split("|")[1:]
        rows = []
        for line in file:
            if line.startswith("Z|ASP|EA|"):  # End of file header
                # TODO: Check number of lines matches?
                break
            rows.append(dict(zip(columns, line.rstrip("\n|").split("|")[1:])))
        else:
            raise RuntimeError("File doesn't conform to the expected format: %s", "Z|ASP|EA|")

        info_stats = {}

        ea_eatt_df = pd.DataFrame(rows)
        info_stats["rows_in_file"] = len(ea_eatt_df)
        column_mapping = {
            # Company identifiers
            "Type d'entreprise adaptée": "kind",
            "Siret de l'établissement membre": "siret",
            "Dénomination / raison sociale": "name",
            # Company owner
            "Courriel du contact étab signataire": "auth_email",
            # Company location
            "Numéro de voie": "address_line_1_part1",
            "Extension de voie": "address_line_1_part2",
            "Code voie": "address_line_1_part3",
            "Libelle de la voie": "address_line_1_part4",
            "Numéro entrée ou batiment": "address_line_2",
            "Code Postal": "post_code",
            "Code INSEE commune": "insee_city",
        }
        ea_eatt_df = remap_columns(ea_eatt_df, column_mapping=column_mapping)

        # Remove "MP" kind as they don't need a PASS and aren't available to the public
        # /!\ The extra space at the end is important to correctly match the field value given to us. /!\
        ea_eatt_df = ea_eatt_df[ea_eatt_df.kind != "Entreprise Adaptée en Milieu Pénitentiaire "]
        info_stats["rows_after_kind_filter"] = len(ea_eatt_df)

        # Convert the data
        ea_eatt_df["kind"] = ea_eatt_df.kind.apply(
            lambda v: {
                "Entreprise Adaptée": CompanyKind.EA,
                "Entreprise Adaptée Travail Temporaire": CompanyKind.EATT,
            }[v]
        )
        ea_eatt_df["name"] = ea_eatt_df.name.apply(str.title)  # "EA LOU JAS" becomes "Ea Lou Jas".
        ea_eatt_df["address_line_1"] = ea_eatt_df.apply(
            lambda row: " ".join(
                filter(
                    None,
                    [
                        row.address_line_1_part1,
                        row.address_line_1_part2,
                        row.address_line_1_part3,
                        row.address_line_1_part4,
                    ],
                )
            ),
            axis="columns",
        )
        ea_eatt_df["insee_city"] = ea_eatt_df.insee_city.apply(lambda v: City.objects.filter(code_insee=v).first())
        # Remove columns that have no purposes anymore
        ea_eatt_df = ea_eatt_df.drop(
            columns=["address_line_1_part1", "address_line_1_part2", "address_line_1_part3", "address_line_1_part4"]
        )

        # Drop duplicate rows, the difference is in the COT/CPOM, but we don't use it for now
        ea_eatt_df = ea_eatt_df.drop_duplicates(
            subset=["kind", "siret"],
            keep="first",
        )
        info_stats["rows_after_deduplication"] = len(ea_eatt_df)

        info_stats["rows_with_a_siret"] = len(ea_eatt_df[~ea_eatt_df.siret.isnull()])
        info_stats["rows_with_empty_email"] = len(ea_eatt_df[ea_eatt_df.auth_email.isnull()])

        info_stats |= sync_structures(
            df=ea_eatt_df,
            source=Company.SOURCE_EA_EATT,
            kinds=[CompanyKind.EA, CompanyKind.EATT],
            build_structure=build_ea_eatt,
            wet_run=wet_run,
        )

        # Display some "stats" about the dataset
        info_stats["rows_used"] = len(ea_eatt_df)
        self.logger.info(
            "%d structures created, %d structures updated, %d structures deleted",
            info_stats["structures_created"],
            info_stats["structures_updated"],
            info_stats["structures_deleted"],
            extra={"info_stats": info_stats},
        )
        if info_stats["not_created_because_of_missing_email"]:
            self.logger.warning(
                "%d structures not created because of missing email",
                info_stats["not_created_because_of_missing_email"],
            )

    @monitor(
        monitor_slug="import-ea-eatt",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 12 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *, from_archive=None, from_asp=False, wet_run=False, **options):
        try:
            archive = self.retrieve_archive_of_the_week() if from_asp else from_archive
        except FileOfTheWeekNotFound:
            if timezone.localdate().isoweekday() >= 5:  # Only raise at end of week (friday)
                raise RuntimeError("No file for this week")
            self.logger.info("No file found, nothing to be done")
            return

        with zipfile.ZipFile(archive).open("EA2_ITOU.txt", pwd=settings.ASP_EA2_UNZIP_PASSWORD.encode()) as f:
            self.process_file(io.TextIOWrapper(f, encoding="utf-8", newline="\n"), wet_run=wet_run)

        if from_asp:
            self.clean_old_archives(wet_run=wet_run)
