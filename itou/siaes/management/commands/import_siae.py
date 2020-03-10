import csv
import logging
import os

from django.core.management.base import BaseCommand

from itou.siaes.models import Siae
from itou.utils.address.departments import DEPARTMENTS
from itou.utils.apis.geocoding import get_geocoding_data

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CSV_FILE = f"{CURRENT_DIR}/data/2019_07_liste_siae.csv"

KINDS = dict(Siae.KIND_CHOICES).keys()

# Below this score, results from `adresse.data.gouv.fr` are considered unreliable.
# This score is arbitrarily set based on general observation.
API_BAN_RELIABLE_MIN_SCORE = 0.6

SEEN_SIRET = set()


class Command(BaseCommand):
    """
    Import SIAEs data into the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_siae --dry-run
        django-admin import_siae --dry-run --verbosity=2

    To populate the database:
        django-admin import_siae
    """

    help = "Import the content of the SIAE csv file into the database."

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
            reader = csv.reader(csvfile, delimiter=";")
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
                    self.stdout.write(f"Creating SIAEs… {progress}%")
                    last_progress = progress

                self.logger.debug("-" * 80)

                siret = row[7]
                self.logger.debug(siret)
                assert len(siret) == 14

                naf = row[5]
                self.logger.debug(naf)
                assert len(naf) == 5

                kind = row[0]
                self.logger.debug(kind)
                assert kind in KINDS

                # Max length of `name` is 50 chars in the source file, some are truncated.
                # Also `name` is in upper case.
                name = row[8].strip()
                name = " ".join(
                    name.split()
                )  # Replace multiple spaces by a single space.
                self.logger.debug(name)

                email = row[14].strip()
                self.logger.debug(email)
                assert " " not in email

                street_num = row[9].strip().replace(" ", "")
                street_name = row[10].strip().lower()
                street_name = " ".join(
                    street_name.split()
                )  # Replace multiple spaces by a single space.
                address_line_1 = f"{street_num} {street_name}"
                address_line_1 = " ".join(
                    address_line_1.split()
                )  # Replace multiple spaces by a single space.
                address_line_2 = ""
                if " - " in address_line_1:
                    addresses = address_line_1.split(" - ")
                    address_line_1 = addresses[0]
                    address_line_2 = addresses[1]
                self.logger.debug(address_line_1)
                self.logger.debug(address_line_2)

                # Fields are identical, we can use one or another.
                post_code = row[3].strip()
                post_code2 = row[11].strip()
                self.logger.debug(post_code)
                assert post_code == post_code2

                # Fields are identical, we can use one or another.
                city = row[4].strip()
                city_name = row[12].strip()
                self.logger.debug(city)
                assert city_name == city

                department = row[1]
                if department[0] == "0":
                    department = department[1:]
                if department in ["59L", "59V"]:
                    department = "59"
                if department not in ["2A", "2B"] and not post_code.startswith(
                    department
                ):
                    # Fix wrong departments using the post code.
                    department = post_code[: len(department)]
                self.logger.debug(department)
                assert department in DEPARTMENTS

                siae_info = f"{siret} {name} - {address_line_1} - {post_code} {city}."

                phone = row[13].strip().replace(" ", "")
                if phone and len(phone) != 10:
                    self.stderr.write(f"Wrong phone `{phone}`. {siae_info}.")
                    phone = ""
                self.logger.debug(phone)

                if siret in SEEN_SIRET:
                    # First come, first served.
                    self.stderr.write(f"Siret already seen. Skipping {siae_info}.")
                    continue
                SEEN_SIRET.add(siret)

                if not dry_run:

                    siae = Siae()
                    siae.siret = siret
                    siae.naf = naf
                    siae.kind = kind
                    siae.source = Siae.SOURCE_ASP
                    siae.name = name
                    siae.phone = phone
                    siae.email = email
                    siae.address_line_1 = address_line_1
                    siae.address_line_2 = address_line_2
                    siae.post_code = post_code
                    siae.city = city
                    siae.department = department

                    if siae.address_on_one_line:

                        geocoding_data = get_geocoding_data(
                            siae.address_on_one_line, post_code=siae.post_code
                        )

                        if not geocoding_data:
                            self.stderr.write(
                                f"No geocoding data found for {siae_info}"
                            )
                            siae.save()
                            continue

                        siae.geocoding_score = geocoding_data["score"]
                        # If the score is greater than API_BAN_RELIABLE_MIN_SCORE, coords are reliable:
                        # use data returned by the BAN API because it's better written using accents etc.
                        # while the source data is in all caps etc.
                        # Otherwise keep the old address (which is probably wrong or incomplete).
                        if siae.geocoding_score >= API_BAN_RELIABLE_MIN_SCORE:
                            siae.address_line_1 = geocoding_data["address_line_1"]
                        else:
                            self.stderr.write(f"Geocoding not reliable for {siae_info}")
                        # City is always good due to `postcode` passed in query.
                        # ST MAURICE DE REMENS => Saint-Maurice-de-Rémens
                        siae.city = geocoding_data["city"]

                        self.logger.debug("-" * 40)
                        self.logger.debug(siae.address_line_1)
                        self.logger.debug(siae.city)

                        siae.coords = geocoding_data["coords"]

                    siae.save()

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
