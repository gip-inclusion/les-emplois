import logging
import os

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

from itou.siaes.management.commands._import_siae.utils import (
    clean_string,
    geocode_siae,
    remap_columns,
    sync_structures,
    timeit,
)
from itou.siaes.models import Siae
from itou.utils.address.departments import department_from_postcode
from itou.utils.validators import validate_siret


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

GEIQ_DATASET_FILENAME = f"{CURRENT_DIR}/data/Geiq_-_liste_02-10-2020.xls"


@timeit
def get_geiq_df(filename=GEIQ_DATASET_FILENAME):
    df = pd.read_excel(filename, converters={"siret": str, "zip": str})

    column_mapping = {
        "Geiq": "name",
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

    return df


def build_geiq(row):
    siae = Siae()
    siae.siret = row.siret
    siae.kind = Siae.KIND_GEIQ
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
        django-admin import_geiq --dry-run --verbosity=2

    To populate the database:
        django-admin import_geiq
    """

    help = "Import the content of the GEIQ csv file into the database."

    def add_arguments(self, parser):
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

    def log(self, message):
        self.stdout.write(message)

    @timeit
    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        geiq_df = get_geiq_df()
        sync_structures(df=geiq_df, name="GEIQ", kinds=[Siae.KIND_GEIQ], build_structure=build_geiq, dry_run=dry_run)

        self.log("-" * 80)
        self.log("Done.")
