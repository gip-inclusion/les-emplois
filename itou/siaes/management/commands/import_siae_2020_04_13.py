"""

This script updates existing SIAEs and injects new ones
by joining the following two ASP datasets:
- Vue Structure (main dataset)
- Liste Correspondants Techniques (secondary dataset)
to build a complete SIAE dataset.

It should be played again after each upcoming Opening (HDF, the whole country...)
and each time we received a new export from the ASP.

Note that we use dataframes instead of csv reader mainly
because the main CSV has a large number of columns (30+)
and thus we need a proper tool to manage columns by their
name instead of hardcoding row numbers as in `field = row[42]`.

"""
import logging
import os

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

from itou.siaes.management.commands.import_deleted_siae import (
    DEPARTMENTS_TO_OPEN_ON_14_04_2020,
    DEPARTMENTS_TO_OPEN_ON_20_04_2020,
    DEPARTMENTS_TO_OPEN_ON_27_04_2020,
)
from itou.siaes.models import Siae
from itou.utils.address.departments import department_from_postcode
from itou.utils.apis.geocoding import get_geocoding_data


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

MAIN_DATASET_FILENAME = f"{CURRENT_DIR}/data/2020_05_11_fluxIAE_Structure_11052020_073452.csv"

SECONDARY_DATASET_FILENAME = f"{CURRENT_DIR}/data/2020_05_07_siae_auth_email_and_external_id.csv"

SIAE_CREATION_ALLOWED_KINDS = [Siae.KIND_ETTI]

SIAE_CREATION_ALLOWED_DEPARTMENTS = (
    DEPARTMENTS_TO_OPEN_ON_14_04_2020 + DEPARTMENTS_TO_OPEN_ON_20_04_2020 + DEPARTMENTS_TO_OPEN_ON_27_04_2020
)

EXPECTED_KINDS = [Siae.KIND_ETTI, Siae.KIND_ACI, Siae.KIND_EI, Siae.KIND_AI]

# Below this score, results from `adresse.data.gouv.fr` are considered unreliable.
# This score is arbitrarily set based on general observation.
API_BAN_RELIABLE_MIN_SCORE = 0.6


def get_main_df(filename=MAIN_DATASET_FILENAME):
    """
    The main dataset is called "Vue Structure" by the ASP
    and has those fields:
    - external_id
    - siret
    - name
    - address
    - phone
    but does *not* have those fields:
    - auth_email
    - kind
    - website (nor is it present in the secondary dataset)
    The fact it does not have auth_email nor kind makes it quite difficult
    to exploit. We have to join it with the secondary dataset, which does
    have auth_email and kind.
    """
    df = pd.read_csv(
        filename,
        sep="|",
        converters={
            "structure_siret_actualise": str,
            "structure_adresse_admin_cp": str,
            "structure_adresse_admin_telephone": str,
        },
    )

    df.rename(
        columns={
            "structure_siret_actualise": "siret",
            "structure_id_siae": "external_id",
            "structure_code_naf": "naf",
            "structure_denomination": "name",
            "structure_adresse_admin_numero": "street_num",
            "structure_adresse_admin_cplt_num_voie": "street_num_extra",
            "structure_adresse_admin_type_voie": "street_type",
            "structure_adresse_admin_nom_voie": "street_name",
            # The extra* fields have very low quality data,
            # their content does not reflect the field name at all.
            "structure_adresse_admin_numero_apt": "extra1",
            "structure_adresse_admin_entree": "extra2",
            "structure_adresse_admin_cplt_adresse": "extra3",
            "structure_adresse_admin_cp": "zipcode",
            "structure_adresse_admin_commune": "city",
            "structure_adresse_admin_telephone": "phone",
        },
        inplace=True,
    )

    for siret in df.siret:
        assert len(siret) == 14

    for naf in df.naf:
        assert len(naf) == 5

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    return df


MAIN_DF = get_main_df()


def get_secondary_df(filename=SECONDARY_DATASET_FILENAME):
    """
    The secondary dataset is called "Liste correspondants techniques" by the ASP
    and only has 5 meaningful columns for us:
    - siret (WARNING : this siret is superseded by MAIN_DF.siret so we don't use it)
    - external_id
    - name (we don't use it though)
    - kind
    - auth_email
    When joined with the first dataset, it somehow constitutes a complete dataset.
    """
    df = pd.read_csv(filename, converters={"siret": str, "auth_email": str}, sep=";")

    # Filter out rows with irrelevant data.
    df = df[df.kind != "FDI"]
    df = df[df.auth_email != "#N/A"]

    # Ignore structure kinds we have not implemented yet.
    df = df[df.kind != "EITI"]

    # Delete superseded siret field to avoid confusion.
    del df["siret"]

    # Delete unused field to avoid confusion.
    del df["name"]

    for kind in df.kind:
        assert kind in EXPECTED_KINDS

    for email in df.auth_email:
        assert " " not in email
        assert "@" in email

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    return df


SECONDARY_DF = get_secondary_df()


def get_df_rows_as_dict(df, external_id):
    rows = df[df.external_id == external_id].to_dict("records")
    return rows


def get_df_row_as_dict(df, external_id):
    rows = get_df_rows_as_dict(df, external_id)
    assert len(rows) <= 1
    return rows[0] if len(rows) == 1 else None


def get_main_df_row_as_dict(external_id):
    return get_df_row_as_dict(MAIN_DF, external_id)


def get_secondary_df_row_as_dict(external_id):
    return get_df_row_as_dict(SECONDARY_DF, external_id)


def get_secondary_df_rows_as_dict(external_id):
    return get_df_rows_as_dict(SECONDARY_DF, external_id)


def should_siae_be_created(siae):
    if siae.kind in SIAE_CREATION_ALLOWED_KINDS:
        return True
    return siae.department in SIAE_CREATION_ALLOWED_DEPARTMENTS


class Command(BaseCommand):
    """
    Update and sync SIAE data based on latest ASP exports.

    To debug:
        django-admin import_siae --verbosity=2 --dry-run

    When ready:
        django-admin import_siae --verbosity=2
    """

    help = "Update and sync SIAE data based on latest ASP exports."

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
        self.logger.debug(message)

    def update_existing_siaes(self, dry_run):
        for siae in Siae.objects.filter(source=Siae.SOURCE_ASP).exclude(external_id__isnull=True):
            row = get_main_df_row_as_dict(external_id=siae.external_id)
            if row:
                if row["siret"] == siae.siret:
                    continue
                else:
                    assert siae.siret[:9] == row["siret"][:9]
                    assert siae.kind in EXPECTED_KINDS
                    self.log(
                        f"siae.id={siae.id} has changed siret from "
                        f"{siae.siret} to {row['siret']} (will be updated)"
                    )
                    if not dry_run:
                        siae.siret = row["siret"]
                        siae.save()
                # FIXME update other fields as well. Or not?
                # Tricky decision since our users may have updated their data
                # themselves and we have no record of that.
            else:
                if siae.members.count():
                    self.log(
                        f"siae.id={siae.id} has members but no longer exists "
                        f"in latest export (should eventually be deleted "
                        f"but not this time)"
                    )
                    # if not dry_run:
                    #     siae.delete()
                else:
                    self.log(
                        f"siae.id={siae.id} no longer exists "
                        f"in latest export (should eventually be deleted "
                        f"but not this time)"
                    )
                    # if not dry_run:
                    #     siae.delete()

    def geocode_siae(self, siae):
        assert siae.address_on_one_line

        geocoding_data = get_geocoding_data(siae.address_on_one_line, post_code=siae.post_code)

        if not geocoding_data:
            self.stderr.write(f"No geocoding data found for siae.external_id={siae.external_id}")
        else:
            siae.geocoding_score = geocoding_data["score"]
            # If the score is greater than API_BAN_RELIABLE_MIN_SCORE, coords are reliable:
            # use data returned by the BAN API because it's better written using accents etc.
            # while the source data is in all caps etc.
            # Otherwise keep the old address (which is probably wrong or incomplete).
            if siae.geocoding_score >= API_BAN_RELIABLE_MIN_SCORE:
                siae.address_line_1 = geocoding_data["address_line_1"]
            else:
                self.stderr.write(f"Geocoding not reliable for siae.external_id={siae.external_id}")
            # City is always good due to `postcode` passed in query.
            # ST MAURICE DE REMENS => Saint-Maurice-de-Rémens
            siae.city = geocoding_data["city"]

            siae.coords = geocoding_data["coords"]

        return siae

    def build_siae(self, main_df_row, secondary_df_row):
        siret = main_df_row["siret"]
        kind = secondary_df_row["kind"]
        external_id = secondary_df_row["external_id"]

        siae = Siae()
        siae.external_id = external_id
        siae.siret = siret
        siae.kind = kind
        siae.naf = main_df_row["naf"]
        siae.source = Siae.SOURCE_ASP
        siae.name = main_df_row["name"]

        siae.phone = main_df_row["phone"]
        if len(siae.phone) != 10:  # As we have faulty 9 digits phones.
            siae.phone = ""  # siae.phone cannot be null in db

        siae.email = ""  # Do not make the authentification email public!
        siae.auth_email = secondary_df_row["auth_email"]

        street_num = main_df_row["street_num"]
        if street_num:
            street_num = int(street_num)
        street_num = f"{street_num or ''} {main_df_row['street_num_extra'] or ''}"
        street_name = f"{main_df_row['street_type'] or ''} {main_df_row['street_name'] or ''}"
        address_line_1 = f"{street_num} {street_name}"
        address_line_1 = " ".join(address_line_1.split())  # Replace multiple spaces by a single space.
        siae.address_line_1 = address_line_1.strip()

        address_line_2 = f"{main_df_row['extra1'] or ''} {main_df_row['extra2'] or ''} {main_df_row['extra3'] or ''}"
        address_line_2 = " ".join(address_line_2.split())  # Replace multiple spaces by a single space.
        siae.address_line_2 = address_line_2.strip()

        # Avoid confusing case where line1 is empty and line2 is not.
        if not siae.address_line_1:
            siae.address_line_1 = siae.address_line_2
            siae.address_line_2 = ""

        siae.city = main_df_row["city"]
        siae.post_code = main_df_row["zipcode"]
        siae.department = department_from_postcode(siae.post_code)

        if should_siae_be_created(siae):
            siae = self.geocode_siae(siae)

        return siae

    def create_new_siaes(self, dry_run):
        external_ids_from_main_df = set(MAIN_DF.external_id.to_list())
        external_ids_from_secondary_df = set(SECONDARY_DF.external_id.to_list())
        external_ids_with_complete_data = external_ids_from_main_df.intersection(external_ids_from_secondary_df)

        creatable_siaes_by_key = {}

        # VERY IMPORTANT : external_id is *not* unique!! o_O
        # Several structures can share the same external_id and in this
        # case they will have the same siret. Note that several structures
        # can share the same external_id, siret *and* kind o_O
        for external_id in external_ids_with_complete_data:

            main_df_row = get_main_df_row_as_dict(external_id=external_id)
            siret = main_df_row["siret"]

            # Several structures share the same external_id in the secondary df.
            secondary_df_rows = get_secondary_df_rows_as_dict(external_id=external_id)

            for secondary_df_row in secondary_df_rows:

                kind = secondary_df_row["kind"]
                for siae in Siae.objects.filter(siret=siret, source=Siae.SOURCE_ASP):
                    if siae.external_id:
                        assert siae.external_id == external_id
                        assert siae.kind in EXPECTED_KINDS
                    elif siae.kind == kind:
                        self.log(f"existing siae.id={siae.id} will be assigned external_id={external_id}")
                        assert siae.kind in EXPECTED_KINDS
                        if not dry_run:
                            siae.external_id = external_id
                            siae.save()

                if Siae.objects.filter(siret=siret, kind=kind).exists():
                    continue
                if not dry_run:
                    if Siae.objects.filter(external_id=external_id, kind=kind).exists():
                        # Siret should have been updated during update_existing_siaes().
                        raise RuntimeError("This should never happen.")

                siae = self.build_siae(main_df_row=main_df_row, secondary_df_row=secondary_df_row)

                if should_siae_be_created(siae):
                    # Gather by unique (siret, kind) key to ensure
                    # avoiding any unicity issue when injecting in db.
                    creatable_siaes_by_key[(siae.siret, siae.kind)] = siae

        creatable_siaes = creatable_siaes_by_key.values()

        self.log("--- beginning of CSV output of all creatable_siaes ---")
        self.log("siret;kind;department;name;external_id;address")
        for siae in creatable_siaes:
            self.log(
                f"{siae.siret};{siae.kind};{siae.department};{siae.name};{siae.external_id};{siae.address_on_one_line}"
            )
        self.log("--- end of CSV output of all creatable_siaes ---")

        self.log(f"{len(creatable_siaes)} structures will be created")
        self.log(f"{len([s for s in creatable_siaes if s.coords])} structures will have geolocation")

        for siae in creatable_siaes:
            if not dry_run:
                siae.save()

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        self.update_existing_siaes(dry_run)

        self.create_new_siaes(dry_run)

        self.log("-" * 80)

        for siae in Siae.objects.all():
            if not siae.has_members and not siae.auth_email:
                msg = (
                    f"Signup is impossible for siae siret={siae.siret} "
                    f"kind={siae.kind} dpt={siae.department} source={siae.source} "
                    f"created_by={siae.created_by} siae_email={siae.email}"
                )
                self.log(msg)

        self.log("-" * 80)

        self.log("Done.")
