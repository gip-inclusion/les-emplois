import argparse
import datetime
import functools
import io
import warnings
import zipfile

import pandas as pd
from django.conf import settings
from django.db import transaction
from django.utils import timezone

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


def convert_kind(raw_kind):
    if raw_kind == "Entreprise Adaptée":
        return CompanyKind.EA
    elif raw_kind == "Entreprise Adaptée Travail Temporaire":
        return CompanyKind.EATT
    raise ValueError(f"Unexpected raw_kind value: {raw_kind}")


@functools.lru_cache
def get_insee_city(code_insee):
    return City.objects.filter(code_insee=code_insee).first()


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


def monday_of_this_week():
    today = timezone.localdate()
    return today - datetime.timedelta(days=today.weekday())


class Command(BaseCommand):
    """
    Import EA and EATT data into the database using the "flux EA2"

    EA = "Entreprise adaptée".
    EATT = "Entreprise adaptée de travail temporaire".
    """

    help = 'Import EA and EATT data into the database using the "flux EA2"'

    def add_arguments(self, parser):
        parser.add_argument("--archive", type=argparse.FileType(mode="rb"), help="The ZIP file")
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def retrieve_archive_of_the_week(self):
        with asp_utils.get_sftp_connection() as sftp:
            self.stdout.write(f'Connected to "{settings.ASP_FS_SFTP_HOST}" as "{settings.ASP_FS_SFTP_USER}"')
            self.stdout.write(f'''Current remote dir is "{sftp.normalize('.')}"''')

            filename_cutoff = f"FLUX_EA2_ITOU_{monday_of_this_week():%Y%m%d}"
            sftp.chdir(REMOTE_DOWNLOAD_DIR)  # Get into the download folder
            file_of_the_week = [filename for filename in sftp.listdir() if filename > filename_cutoff]
            if not file_of_the_week:
                raise RuntimeError("No file for this week: %s", filename_cutoff)
            if len(file_of_the_week) > 1:
                raise RuntimeError("Too many files for this week: %r", file_of_the_week)

            file = io.BytesIO()
            sftp.getfo(file_of_the_week[0], file)
            return file

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

        # Convert the data
        ea_eatt_df["kind"] = ea_eatt_df.kind.apply(convert_kind)
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
        ea_eatt_df["insee_city"] = ea_eatt_df.insee_city.apply(get_insee_city)
        # Remove columns that have no purposes anymore
        ea_eatt_df = ea_eatt_df.drop(
            columns=["address_line_1_part1", "address_line_1_part2", "address_line_1_part3", "address_line_1_part4"]
        )

        info_stats |= sync_structures(
            df=ea_eatt_df,
            source=Company.SOURCE_EA_EATT,
            kinds=[CompanyKind.EA, CompanyKind.EATT],
            build_structure=build_ea_eatt,
            wet_run=wet_run,
        )

        # Display some "stats" about the dataset
        self.stdout.write("-" * 80)
        self.stdout.write(f"Rows in file: {info_stats['rows_in_file']}")
        self.stdout.write(f"Rows with a SIRET: {info_stats['rows_with_a_siret']}")
        self.stdout.write(f"Rows after deduplication: {info_stats['rows_after_deduplication']}")
        self.stdout.write(f"Rows with a convention not expired: {info_stats['rows_with_a_valid_convention']}")
        self.stdout.write(f"Rows used: {len(ea_eatt_df)}")
        self.stdout.write(f" > With an empty email: {info_stats['rows_with_empty_email']}")
        self.stdout.write(f" > Creatable: {info_stats['creatable_sirets']}")
        self.stdout.write(f" >> Created: {info_stats['structures_created']}")
        self.stdout.write(
            f" >> Not created because of missing email: {info_stats['not_created_because_of_missing_email']}"
        )
        self.stdout.write(f" > Updatable: {info_stats['updatable_sirets']}")
        self.stdout.write(f" >> Updated: {info_stats['structures_updated']}")
        self.stdout.write(f" > Deletable: {info_stats['deletable_sirets']}")
        self.stdout.write(f" >> Deleted: {info_stats['structures_deleted']}")
        self.stdout.write(f" >> Undeletable: {info_stats['structures_undeletable']}")
        self.stdout.write(f" >> Skipped: {info_stats['structures_deletable_skipped']}")
        self.stdout.write("-" * 80)
        self.stdout.write("Done.")

        if info_stats["rows_with_empty_email"] > 20:
            warnings.warn(f"Too many missing emails: {info_stats['rows_with_empty_email']}")
        if info_stats["not_created_because_of_missing_email"]:
            warnings.warn(
                f"Structure(s) not created because of a missing email: "
                f"{info_stats['not_created_because_of_missing_email']}"
            )

    @transaction.atomic
    def handle(self, *, archive=None, wet_run=False, **options):
        if not archive:
            archive = self.retrieve_archive_of_the_week()

        with zipfile.ZipFile(archive).open("EA2_ITOU.txt", pwd=settings.ASP_EA2_UNZIP_PASSWORD.encode()) as file:
            self.process_file(io.TextIOWrapper(file, encoding="utf-8", newline="\n"), wet_run=wet_run)

        # TODO: Clean files on the SFTP

        # raise Exception()
