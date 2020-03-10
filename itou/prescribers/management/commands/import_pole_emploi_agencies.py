import csv
import logging
import os

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand

from itou.prescribers.models import PrescriberOrganization
from itou.utils.address.departments import DEPARTMENTS

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CSV_FILE = f"{CURRENT_DIR}/data/pole_emploi_agencies.csv"


class Command(BaseCommand):
    """
    Import Pole emploi agencies (prescriber organizations) data into
    the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_pole_emploi_agencies --dry-run
        django-admin import_pole_emploi_agencies --dry-run --verbosity=2

    To populate the database:
        django-admin import_pole_emploi_agencies
    """

    help = (
        "Import the content of the prescriber organizations csv file into the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Only print data to import",
        )

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

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        with open(CSV_FILE) as csvfile:

            # Count lines in CSV.
            reader = csv.reader(csvfile, delimiter=",")
            row_count = sum(1 for row in reader)
            last_progress = 0
            # Reset the iterator to iterate through the reader again.
            csvfile.seek(0)

            for i, row in enumerate(reader):

                if i == 0:
                    # Skip CSV header.
                    continue

                progress = int((100 * i) / row_count)
                if progress > last_progress + 5:
                    self.stdout.write(f"Creating prescriber organizations… {progress}%")
                    last_progress = progress

                self.logger.debug("-" * 80)

                name = f"POLE EMPLOI - {row[1].strip().upper()}"
                self.logger.debug(name)

                code_safir = row[2].strip()
                assert code_safir.isdigit()
                assert len(code_safir) == 5
                self.logger.debug(code_safir)

                address_line_1 = row[8].strip()
                self.logger.debug(address_line_1)

                city = row[10].strip()
                self.logger.debug(city)

                post_code = row[9].strip()
                self.logger.debug(post_code)

                if post_code.startswith("20"):
                    if post_code.startswith("200") or post_code.startswith("201"):
                        department = "2A"
                    elif post_code.startswith("202"):
                        department = "2B"
                elif post_code.startswith("97") or post_code.startswith("98"):
                    department = post_code[:3]
                else:
                    department = post_code[:2]
                self.logger.debug(department)
                assert department in DEPARTMENTS

                latitude = row[11].strip().replace(",", ".")
                self.logger.debug(latitude)

                longitude = row[12].strip().replace(",", ".")
                self.logger.debug(longitude)

                if not dry_run:

                    PrescriberOrganization.objects.get_or_create(
                        code_safir_pole_emploi=code_safir,
                        defaults={
                            "is_authorized": True,
                            "name": name,
                            "address_line_1": address_line_1,
                            "post_code": post_code,
                            "city": city,
                            "department": department,
                            "coords": GEOSGeometry(f"POINT({longitude} {latitude})"),
                        },
                    )

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
