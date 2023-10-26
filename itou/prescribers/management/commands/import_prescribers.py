import csv
import logging
import os

from itou.common.address.departments import DEPARTMENTS
from itou.common_apps.apis.geocoding import get_geocoding_data
from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.command import BaseCommand


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CSV_FILE = f"{CURRENT_DIR}/data/authorized_prescribers.csv"


class Command(BaseCommand):
    """
    Import prescriber organizations data into the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_prescribers --dry-run
        django-admin import_prescribers --dry-run --verbosity=2

    To populate the database:
        django-admin import_prescribers
    """

    help = "Import the content of the prescriber organizations csv file into the database."

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

    def handle(self, *, dry_run, **options):
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

                city = row[7].strip()
                self.logger.debug(city)

                department = row[0].strip()
                assert department in DEPARTMENTS
                self.logger.debug(department)

                name = row[1].strip()
                if name == "MISSION LOCALE":
                    name = f"{name} - {city}"
                elif name in [
                    "CAP EMPLOI",
                    "DIRECTION TERRITORIALE DE LA PROTECTION JUDICIAIRE DE LA JEUNESSE",
                    "POLE EMPLOI",
                    "SERVICE PENITENTIAIRE D'INSERTION ET DE PROBATION",
                ]:
                    name = f"{name} - {department}"
                self.logger.debug(name)

                phone = row[10].strip()
                if phone:
                    assert len(phone) == 10
                    self.logger.debug(phone)

                email = row[9].strip()
                self.logger.debug(email)

                website = row[11].strip()
                self.logger.debug(website)

                post_code = row[6].strip()
                self.logger.debug(post_code)

                address_line_1 = row[2].strip()
                self.logger.debug(address_line_1)

                complement = row[3].strip()
                complement_2 = row[4].strip()
                bp_cs = row[5].strip()
                cedex = row[8].strip()
                address_line_2 = [complement, complement_2, bp_cs, cedex]
                address_line_2 = " - ".join(item for item in address_line_2 if item)
                self.logger.debug(address_line_2)

                if not dry_run:
                    prescriber_organization = PrescriberOrganization()

                    prescriber_organization.is_authorized = True
                    prescriber_organization.name = name
                    prescriber_organization.phone = phone
                    prescriber_organization.email = email
                    prescriber_organization.website = website
                    prescriber_organization.address_line_1 = address_line_1
                    prescriber_organization.address_line_2 = address_line_2
                    prescriber_organization.post_code = post_code
                    prescriber_organization.city = city
                    prescriber_organization.department = department

                    try:
                        geocoding_data = get_geocoding_data(
                            "{}, {} {}".format(
                                prescriber_organization.address_line_1,
                                prescriber_organization.post_code,
                                prescriber_organization.city,
                            )
                        )
                        prescriber_organization.coords = geocoding_data["coords"]
                    except GeocodingDataError:
                        prescriber_organization.coords = ""

                    prescriber_organization.save()

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
