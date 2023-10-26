"""
This script exports ASP reference files into fixtures.

This could be a "one shot" action but we don't know for sure
if these reference files are likely to change.
"""
import json
import os
from datetime import datetime

import pandas as pd
from django.conf import settings

from itou.utils.command import BaseCommand
from itou.utils.management_commands import DeprecatedLoggerMixin


_FIXTURES_DIR = "itou/asp/fixtures"
_SEP = ";"
_ASP_DATE_FORMAT = "%d/%m/%Y"


def parse_asp_date(dt):
    # Sometimes import files have a / instead of empty string for end dates
    if dt and dt != "/":
        return str(datetime.strptime(dt, _ASP_DATE_FORMAT).date())
    return None


class Command(DeprecatedLoggerMixin, BaseCommand):
    """
    Generation of ASP reference files fixtures

    Modus operandi:
    - put the ASP files to import in the 'imports' folder
    - run command via: ./manage.py gen_asp_ref_fixtures --verbosity=2

    OR

    select one or more files to import explicitly:
    ./manage.py gen_asp_ref_fixtures --verbosity=2 --education_levels=myfile.csv ...

    Files still have to be in 'import' folder.

    A 'dry-run' parameter is also available:
    ./manage.py gen_asp_ref_fixtures --verbosity=2 --dry-run

    With 'dry-run', all operations but file storage are processed.

    Once generated, fixtures can be imported via:
    ./manage.py loaddata --app asp itou/asp/fixtures/*.json

    Check 'itou.asp.models' for details.
    """

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to import")
        parser.add_argument("--insee_communes")
        parser.add_argument("--insee_departments")
        parser.add_argument("--insee_countries")
        parser.add_argument("--siae_kinds")

    def log(self, message):
        self.logger.debug(message)

    def load_dataframe(self, path, separator=_SEP):
        self.log(f"Creating dataframe from file: {path}")
        df = pd.read_csv(path, sep=separator)
        df = df.where(pd.notnull(df), None)
        self.log(df)
        return df

    def write_fixture_file(self, path, records):
        """
        Write fixture file
        filename_prefix add a prefix to the filename for ordering concerns
        if any (i.e. for CompanyKind objects references)
        """
        self.log(f"Formatted {len(records)} element(s)")
        self.log(f"Writing JSON fixture to: {path}")

        if not self.dry_run:
            with open(path, "w") as of:
                of.write(json.dumps(records, indent=3))
        else:
            self.log("joking: DRY-RUN enabled")
        self.log("Done!")
        self.log("-" * 80)

    def file_exists(self, path):
        if os.path.isfile(path):
            self.log(f"Found input file '{path}'")
            return True
        self.log("No import file found. Skipping.")
        self.log("-" * 80)
        return False

    def gen_insee_communes(self, filename="ref_insee_com.csv"):
        """
        Generates ASP INSEE communes fixture.

        Important:
        This list of communes is not the same as the official INSEE one.
        There is a reconciliation mechanism to implement
        """
        path = os.path.join(settings.IMPORT_DIR, filename)

        self.log("Importing ASP INSEE communes:\n")

        if not self.file_exists(path):
            return

        export_path = os.path.join(_FIXTURES_DIR, "asp_INSEE_communes.json")
        model = "asp.Commune"
        df = self.load_dataframe(path)
        records = []

        for idx, row in df.iterrows():
            start_date = parse_asp_date(row["DATE_DEB_INSEE"])
            end_date = parse_asp_date(row["DATE_FIN_INSEE"])

            elt = {
                "model": model,
                "pk": idx + 1,
                "fields": {
                    "code": row["CODE_COM_INSEE"],
                    "name": row["LIB_COM"],
                    "start_date": start_date,
                    "end_date": end_date,
                },
            }
            records.append(elt)

        self.write_fixture_file(export_path, records)

    def gen_insee_departments(self, filename="ref_insee_dpt.csv"):
        """
        Generates ASP INSEE department fixture.

        Important:
        This list of departments is not the same as the official INSEE one.
        There is a reconciliation mechanism to implement
        """
        path = os.path.join(settings.IMPORT_DIR, filename)

        self.log("Importing ASP INSEE departments:\n")

        if not self.file_exists(path):
            return

        export_path = os.path.join(_FIXTURES_DIR, "asp_INSEE_departments.json")
        model = "asp.Department"
        df = self.load_dataframe(path)
        records = []

        for idx, row in df.iterrows():
            start_date = parse_asp_date(row["DATE_DEB_DPT"])
            end_date = parse_asp_date(row["DATE_FIN_DPT"])

            elt = {
                "model": model,
                "pk": idx + 1,
                "fields": {
                    "code": row["CODE_DPT"],
                    "name": row["LIB_DPT"],
                    "start_date": start_date,
                    "end_date": end_date,
                },
            }
            records.append(elt)

        self.write_fixture_file(export_path, records)

    def gen_insee_countries(self, filename="ref_insee_pays.csv"):
        """
        Generates ASP INSEE countries fixture.

        This list of countries is not the same as the official INSEE one.
        In this specific case, we don't care. Itou is France-centric
        """
        path = os.path.join(settings.IMPORT_DIR, filename)

        self.log("Importing ASP INSEE countries:\n")

        if not self.file_exists(path):
            return

        export_path = os.path.join(_FIXTURES_DIR, "asp_INSEE_countries.json")
        model = "asp.Country"
        df = self.load_dataframe(path)
        records = []

        for idx, row in df.iterrows():
            elt = {
                "model": model,
                "pk": idx + 1,
                "fields": {
                    "code": row["CODE_INSEE_PAYS"],
                    "name": row["LIB_INSEE_PAYS"],
                    "group": row["CODE_GROUPE_PAYS"],
                    # For compatibility, no usage right now
                    "department": row["CODE_DPT"],
                },
            }
            records.append(elt)

        self.write_fixture_file(export_path, records)

    def gen_siae_kinds(self, filename="ref_mesure.csv"):
        """
        Generates ASP SIAE kinds fixture.

        Fixture prefix is important for this case, because CompanyKind must be
        imported before EducationLevel and EmployerType entries
        """
        path = os.path.join(settings.IMPORT_DIR, filename)

        self.log("Importing ASP SIAE kinds:\n")

        if not self.file_exists(path):
            return

        export_path = os.path.join(_FIXTURES_DIR, "asp_siae_kinds.json")
        model = "asp.CompanyKind"
        df = self.load_dataframe(path)
        records = []

        for idx, row in df.iterrows():
            start_date = parse_asp_date(row["Rme_date_debut_effet"])
            end_date = parse_asp_date(row["Rme_date_fin_effet"])
            elt = {
                "model": model,
                "pk": row["Rme_id"],
                "fields": {
                    "code": row["Rme_code_mesure_disp"],
                    "display_code": row["Rme_code_mesure"],
                    "help_code": row["Rme_code_aide"],
                    "name": row["Rme_libelle_mesure"],
                    # For compatibility, no usage right now
                    "rdi_id": row["Rdi_id"],
                    "start_date": start_date,
                    "end_date": end_date,
                },
            }
            records.append(elt)

        self.write_fixture_file(export_path, records)

    def handle(self, *, dry_run, **options):
        self.dry_run = dry_run
        self.set_logger(options.get("verbosity"))

        partial = [
            elt
            for elt in [
                "insee_communes",
                "insee_departments",
                "insee_countries",
                "siae_kinds",
            ]
            if options.get(elt)
        ]

        if len(partial) > 1:
            self.logger.error("ERROR: Only one file import argument is allowed, %s provided.", len(partial))
            return

        if partial:
            import_arg = partial[0]
            fn = getattr(self, f"gen_{import_arg}")
            fn(filename=options.get(import_arg))
        else:
            self.gen_insee_communes()
            self.gen_insee_departments()
            self.gen_insee_countries()
            self.gen_siae_kinds()
