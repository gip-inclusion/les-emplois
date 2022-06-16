import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

from itou.common_apps.address.departments import department_from_postcode
from itou.siaes.enums import SiaeKind
from itou.siaes.management.commands._import_siae.utils import (
    clean_string,
    geocode_siae,
    get_filename,
    remap_columns,
    sync_structures,
    timeit,
)
from itou.siaes.models import Siae
from itou.utils.validators import validate_siret


@timeit
def get_geiq_df():
    filename = get_filename(filename_prefix="Liste_Geiq", filename_extension=".xls", description="Export GEIQ")

    df = pd.read_excel(filename, converters={"siret": str, "zip": str})

    column_mapping = {
        "name": "name",
        "street": "address_line_1",
        "street2": "address_line_2",
        "zip": "post_code",
        "city": "city",
        "siret": "siret",
        "email": "auth_email",
    }
    df = remap_columns(df, column_mapping=column_mapping)

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

    # Drop rows without auth_email.
    df = df[~df.auth_email.isnull()]

    for _, row in df.iterrows():
        validate_siret(row.siret)

    assert df.siret.is_unique
    assert len(df) >= 150  # Export usually has 180+ geiq structures.

    return df


def build_geiq(row):
    siae = Siae()
    siae.siret = row.siret
    siae.kind = SiaeKind.GEIQ
    siae.source = Siae.SOURCE_GEIQ
    siae.name = row["name"]  # row.name returns row index.
    assert not siae.name.isnumeric()
    siae.email = ""  # Do not make the authentification email public!
    siae.auth_email = row.auth_email
    siae.address_line_1 = row.address_line_1
    siae.address_line_2 = ""
    if row.address_line_2:
        siae.address_line_2 = row.address_line_2
    siae.post_code = row.post_code
    siae.city = row.city
    siae.department = row.department

    siae = geocode_siae(siae)

    return siae


class Command(BaseCommand):
    """
    Import GEIQs data into the database.
    This command is meant to be used before any fixture is available.

    GEIQ = "Groupement d'Employeurs pour l'Insertion et la Qualification".

    To debug:
        django-admin import_geiq --dry-run

    To populate the database:
        django-admin import_geiq
    """

    help = "Import the content of the GEIQ csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to import")

    @timeit
    def handle(self, dry_run=False, **options):
        geiq_df = get_geiq_df()
        sync_structures(
            df=geiq_df, source=Siae.SOURCE_GEIQ, kinds=[SiaeKind.GEIQ], build_structure=build_geiq, dry_run=dry_run
        )

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
