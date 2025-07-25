import numpy as np
import pandas as pd
from django.core.management.base import CommandError

from itou.common_apps.address.departments import department_from_postcode
from itou.companies.enums import CompanyKind
from itou.companies.management.commands._import_siae.utils import (
    clean_string,
    geocode_siae,
    remap_columns,
    sync_structures,
)
from itou.companies.models import Company
from itou.utils.command import BaseCommand
from itou.utils.python import timeit
from itou.utils.validators import validate_siret


@timeit
def get_geiq_df(filename):
    info_stats = {}

    df = pd.read_excel(filename, converters={"siret": str, "zip": str})
    info_stats["rows_in_file"] = len(df)

    column_mapping = {
        "Nom": "name",
        "Rue": "address_line_1",
        "Rue (suite)": "address_line_2",
        "Code Postal": "post_code",
        "Ville": "city",
        "SIRET": "siret",
        "e-mail": "auth_email",
    }
    df = remap_columns(df, column_mapping=column_mapping)

    # Force siret type to integer, otherwise replacing NaN elements to None blindly converts them to float.
    df["siret"] = df["siret"].astype("Int64")

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    # Clean string fields.
    df["name"] = df.name.apply(clean_string)
    df["address_line_1"] = df.address_line_1.apply(clean_string)
    df["address_line_2"] = df.address_line_2.apply(clean_string)
    df["post_code"] = df.post_code.apply(clean_string)
    df["city"] = df.city.apply(clean_string)
    df["siret"] = df.siret.apply(clean_string)
    df["auth_email"] = df.auth_email.apply(clean_string)

    # "GEIQ PROVENCE" becomes "Geiq Provence".
    df["name"] = df.name.apply(str.title)

    df["department"] = df.post_code.apply(department_from_postcode)

    # Drop rows without siret.
    df = df[~df.siret.isnull()]
    info_stats["rows_with_a_siret"] = len(df)

    df.drop_duplicates(
        subset=["siret"],
        keep="first",
        inplace=True,
    )
    info_stats["rows_after_deduplication"] = len(df)

    # Drop rows without auth_email.
    info_stats["rows_with_empty_email"] = len(df[df.auth_email.isnull()])
    df = df[~df.auth_email.isnull()]

    for _, row in df.iterrows():
        validate_siret(row.siret)

    assert df.siret.is_unique
    assert len(df) >= 150  # Export usually has 180+ geiq structures.

    return df, info_stats


def build_geiq(row):
    company = Company()
    company.siret = row.siret
    company.kind = CompanyKind.GEIQ
    company.source = Company.SOURCE_GEIQ
    company.name = row["name"]  # row.name returns row index.
    assert not company.name.isnumeric()
    company.email = ""  # Do not make the authentification email public!
    company.auth_email = row.auth_email
    company.address_line_1 = row.address_line_1
    company.address_line_2 = ""
    if row.address_line_2:
        company.address_line_2 = row.address_line_2
    company.post_code = row.post_code
    company.city = row.city
    company.department = row.department

    geocode_siae(company)
    return company


class Command(BaseCommand):
    """
    Import GEIQs data into the database.
    This command is meant to be used before any fixture is available.

    GEIQ = "Groupement d'Employeurs pour l'Insertion et la Qualification".

    To debug:
        django-admin import_geiq

    To populate the database:
        django-admin import_geiq --wet-run
    """

    ATOMIC_HANDLE = True

    help = "Import the content of the GEIQ csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument("filename")
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @timeit
    def handle(self, *, filename, wet_run, **options):
        geiq_df, info_stats = get_geiq_df(filename)
        info_stats |= sync_structures(
            df=geiq_df,
            source=Company.SOURCE_GEIQ,
            kinds=[CompanyKind.GEIQ],
            build_structure=build_geiq,
            wet_run=wet_run,
        )

        # Display some "stats" about the dataset
        self.stdout.write("-" * 80)
        self.stdout.write(f"Rows in file: {info_stats['rows_in_file']}")
        self.stdout.write(f"Rows with a SIRET: {info_stats['rows_with_a_siret']}")
        self.stdout.write(f"Rows with an empty email: {info_stats['rows_with_empty_email']}")
        self.stdout.write(f"Rows used: {len(geiq_df)}")
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

        warning_messages = []
        if info_stats["rows_with_empty_email"] > 20:
            warning_messages.append(f"Too many missing emails: {info_stats['rows_with_empty_email']}")
        if info_stats["not_created_because_of_missing_email"]:
            warning_messages.append(
                f"Structure(s) not created because of a missing email: "
                f"{info_stats['not_created_because_of_missing_email']}"
            )
        if warning_messages:
            raise CommandError("\n".join(warning_messages))
