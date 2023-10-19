import datetime
import warnings

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

from itou.common_apps.address.departments import department_from_postcode
from itou.companies.enums import CompanyKind
from itou.companies.management.commands._import_siae.utils import (
    clean_string,
    geocode_siae,
    get_filename,
    remap_columns,
    sync_structures,
)
from itou.companies.models import Siae
from itou.utils.python import timeit
from itou.utils.validators import validate_siret


def convert_kind(raw_kind):
    if raw_kind == "Entreprise Adaptée":
        return CompanyKind.EA
    elif raw_kind == "Entreprise Adaptée Travail Temporaire":
        return CompanyKind.EATT
    raise ValueError(f"Unexpected raw_kind value: {raw_kind}")


@timeit
def get_ea_eatt_df():
    info_stats = {}
    filename = get_filename(
        filename_prefix="Liste_Contact_EA", filename_extension=".xlsx", description="Export EA/EATT"
    )

    siret_field_name = "Siret_Signataire"
    post_code_field_name = "CODE_POST_Signataire"
    phone_field_name = "TEL_CONT_Signataire"
    convention_end_date_field_name = "Date_Fin_App_Etab_Membre"

    df = pd.read_excel(
        filename,
        converters={
            siret_field_name: str,
            post_code_field_name: str,
            phone_field_name: str,
            convention_end_date_field_name: datetime.date.fromisoformat,
        },
    )
    info_stats["rows_in_file"] = len(df)

    column_mapping = {
        "Denomination_Sociale_Signataire": "name",
        "LIB_TYPE_EA": "kind",
        "NUM_ENTREE_Signataire": "address_part1",
        "NUM_VOIE_Signataire": "address_part2",
        "CODE_VOIE_Signataire": "address_part3",
        "LIB_VOIE_Signataire": "address_part4",
        post_code_field_name: "post_code",
        "LIB_COM_Signataire": "city",
        siret_field_name: "siret",
        "CRL_CONT_Signataire": "auth_email",
        phone_field_name: "phone",
        convention_end_date_field_name: "convention_end_date",
    }
    df = remap_columns(df, column_mapping=column_mapping)

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    df = df[df.kind != "Entreprise Adaptée en Milieu Pénitentiaire"]

    # note (fv): apparently, EA / EATT XLS source file can also contain the following field value
    # (which is the same as the line above, on a business POV)
    df = df[df.kind != "Entreprise Adaptée en Etablissement Pénitentiaire"]

    df["kind"] = df.kind.apply(convert_kind)

    # Drop rows without siret.
    df = df[~df.siret.isnull()]
    info_stats["rows_with_a_siret"] = len(df)

    df.drop_duplicates(
        subset=["siret"],
        keep="first",
        inplace=True,
    )
    info_stats["rows_after_deduplication"] = len(df)

    # Drop the rows with an expired convention
    df = df[df["convention_end_date"] > datetime.date.today()]
    info_stats["rows_with_a_valid_convention"] = len(df)

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

    info_stats["rows_with_empty_email"] = len(df[df.auth_email.isnull()])

    assert df.siret.is_unique
    assert len(df) >= 600, f"Export usually has 700+ EA/EATT structures (only {len(df)})."

    return df, info_stats


def build_ea_eatt(row):
    siae = Siae()
    siae.siret = row.siret
    siae.kind = row.kind
    assert siae.kind in [CompanyKind.EA, CompanyKind.EATT]
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

    To populate the database:
        django-admin import_ea_eatt
    """

    help = "Import the content of the EA+EATT csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @timeit
    def handle(self, *, wet_run, **options):
        ea_eatt_df, info_stats = get_ea_eatt_df()
        info_stats |= sync_structures(
            df=ea_eatt_df,
            source=Siae.SOURCE_EA_EATT,
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
