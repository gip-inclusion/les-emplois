"""
This script exports ASP reference files into fixtures

This could be a "one shot" but we don't know for sure if this
reference files are likely to change
"""
import json
import logging
import os
from datetime import datetime

import pandas as pd
from django.core.management.base import BaseCommand


_IMPORT_DIR = "imports"
_FIXTURES_DIR = "itou/asp/fixtures"
_SEP = ";"
_DATE_FORMAT = "%d/%m/%Y"


class Command(BaseCommand):
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

    def gen_training_levels(self, filename="ref_niveau_formation.csv"):
        """
        Generate ASP training level fixture
        """
        path = os.path.join(_IMPORT_DIR, filename)
        export_path = os.path.join(_FIXTURES_DIR, "EducationLevel.json")
        model = "asp.EducationLevel"

        self.log(f"Import path: {path}")
        df = pd.read_csv(path, sep=_SEP)
        df = df.where(pd.notnull(df), None)

        print(df)

        result = []
        for idx, row in df.iterrows():
            start_date = datetime.strptime(row["rte_date_debut_effet"], _DATE_FORMAT).date()
            end_date = (
                datetime.strptime(row["rte_date_fin_effet"], _DATE_FORMAT).date()
                if row["rte_date_fin_effet"]
                else None
            )

            elt = {
                "model": model,
                "pk": row["rnf_id"],
                "fields": {
                    "code": row["rnf_code_form_empl"],
                    "name": row["rnf_libelle_niveau_form_empl"],
                    "start_date": str(start_date),
                    "end_date": str(end_date) if end_date else None,
                },
            }
            result.append(elt)

        self.log(f"Writing result to: {export_path}")
        if not self.dry_run:
            with open(export_path, "w") as of:
                of.write(json.dumps(result))

        print(result)

    def handle(self, dry_run=False, **options):
        self.dry_run = dry_run
        self.set_logger(options.get("verbosity"))

        self.gen_training_levels()
