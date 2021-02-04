import logging

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

from itou.siaes.management.commands._import_siae.utils import (
    clean_string,
    geocode_siae,
    get_filename,
    remap_columns,
    sync_structures,
    timeit,
)
from itou.siaes.models import Siae
from itou.utils.address.departments import department_from_postcode
from itou.utils.validators import validate_siret


def convert_kind(raw_kind):
    if raw_kind == "Entreprise adaptee":
        return Siae.KIND_EA
    elif raw_kind == "EA Travail Temporaire":
        return Siae.KIND_EATT
    raise ValueError("Unexpected raw_kind")


@timeit
def get_ea_eatt_df():
    filename = get_filename(
        filename_prefix="Liste_Contact_EA", filename_extension=".xlsx", description="Export EA/EATT"
    )

    df = pd.read_excel(filename, converters={"SIRET": str, "CODE_POST": str})

    column_mapping = {
        "RAISON_SCLE": "name",
        "TYPE_EA": "kind",
        "NUM_ENTREE": "address_part1",
        "NUM_VOIE": "address_part2",
        "CODE_VOIE": "address_part3",
        "LIB_VOIE": "address_part4",
        "CODE_POST": "post_code",
        "LIB_COM": "city",
        "SIRET": "siret",
        "CRL_CONT": "auth_email",
        "TEL_CONT": "phone",
    }
    df = remap_columns(df, column_mapping=column_mapping)

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    df["kind"] = df.kind.apply(convert_kind)

    # Drop rows without siret.
    df = df[~df.siret.isnull()]

    df["address_line_1"] = ""

    for _, row in df.iterrows():
        validate_siret(row.siret)
        address_line_1 = ""
        if row.address_part1:
            address_line_1 += row.address_part1
        if row.address_part2:
            address_line_1 += f" {int(row.address_part2)}"
        if row.address_part3:
            address_line_1 += f" {row.address_part3}"
        if row.address_part4:
            address_line_1 += f" {row.address_part4}"
        row["address_line_1"] = address_line_1

    # Clean string fields.
    df["name"] = df.name.apply(clean_string)
    df["kind"] = df.kind.apply(clean_string)
    df["address_line_1"] = df.address_line_1.apply(clean_string)
    df["post_code"] = df.post_code.apply(clean_string)
    df["city"] = df.city.apply(clean_string)
    df["siret"] = df.siret.apply(clean_string)
    df["auth_email"] = df.auth_email.apply(clean_string)
    df["phone"] = df.phone.apply(clean_string)

    # "EA LOU JAS" becomes "Ea Lou Jas".
    df["name"] = df.name.apply(str.title)

    df["department"] = df.post_code.apply(department_from_postcode)

    # Drop rows without auth_email.
    df = df[~df.auth_email.isnull()]

    assert df.siret.is_unique
    assert len(df) >= 600  # Export usually has 700+ ea/eatt structures.

    return df


def build_ea_eatt(row):
    siae = Siae()
    siae.siret = row.siret
    siae.kind = row.kind
    siae.source = Siae.SOURCE_EA_EATT

    siae.name = row["name"]  # row.name returns row index.
    assert not siae.name.isnumeric()

    siae.email = ""  # Do not make the authentification email public!
    siae.auth_email = row.auth_email

    siae.phone = row.phone.replace(" ", "").replace(".", "") if row.phone else ""
    phone_is_valid = siae.phone and len(siae.phone) == 10
    if not phone_is_valid:
        siae.phone = ""  # siae.phone cannot be null in db

    siae.address_line_1 = row.address_line_1
    siae.address_line_2 = ""
    siae.post_code = row.post_code
    siae.city = row.city
    siae.department = row.department

    siae = geocode_siae(siae)

    return siae


class Command(BaseCommand):
    """
    Import EA and EATT data into the database.
    This command is meant to be used before any fixture is available.

    EA = "Entreprise adaptée".
    EATT = "Entreprise adaptée de travail temporaire".

    To debug:
        django-admin import_ea_eatt --dry-run
        django-admin import_ea_eatt --dry-run --verbosity=2

    To populate the database:
        django-admin import_ea_eatt
    """

    help = "Import the content of the EA+EATT csv file into the database."

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

        ea_eatt_df = get_ea_eatt_df()
        sync_structures(
            df=ea_eatt_df,
            name="EA and EATT",
            kinds=[Siae.KIND_EA, Siae.KIND_EATT],
            build_structure=build_ea_eatt,
            dry_run=dry_run,
        )

        self.log("-" * 80)
        self.log("Done.")
