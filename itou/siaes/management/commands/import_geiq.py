import csv
import logging
import os

from django.core.management.base import BaseCommand

from itou.siaes.models import Siae
from itou.utils.address.departments import DEPARTMENTS
from itou.utils.apis.geocoding import get_geocoding_data

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CSV_FILE = f"{CURRENT_DIR}/data/2019_11_21_export_bbd_geiq.csv"

KINDS = dict(Siae.KIND_CHOICES).keys()

# Below this score, results from `adresse.data.gouv.fr` are considered unreliable.
# This score is arbitrarily set based on general observation.
API_BAN_RELIABLE_MIN_SCORE = 0.6

SEEN_SIRET = set()


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

            reader = csv.reader(csvfile, delimiter=";")

            for i, row in enumerate(reader):

                if i == 0:
                    # Skip CSV header.
                    continue

                self.logger.debug("-" * 80)

                name = row[0].strip()
                name = " ".join(
                    name.split()
                )  # Replace multiple spaces by a single space.
                self.logger.debug(name)

                address_line_1 = row[1].strip()
                address_line_1 = " ".join(address_line_1.split())
                self.logger.debug(address_line_1)

                address_line_2 = row[2].strip()
                address_line_2 = " ".join(address_line_2.split())
                self.logger.debug(address_line_2)

                city = row[3].strip()
                city = " ".join(city.split())
                self.logger.debug(city)

                post_code = row[4].strip()
                post_code = " ".join(post_code.split())
                self.logger.debug(post_code)

                email = row[5].strip()
                self.logger.debug(email)
                assert " " not in email

                phone = row[6].strip().replace(" ", "")
                assert len(phone) == 10
                self.logger.debug(phone)

                naf = row[7]
                self.logger.debug(naf)
                if naf:
                    assert len(naf) == 5

                siret = row[8].strip()
                self.logger.debug(siret)
                assert len(siret) == 14

                if siret in SEEN_SIRET:
                    self.stderr.write(f"Siret already seen. Skipping.")
                    continue
                SEEN_SIRET.add(siret)

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

                siae_info = f"{siret} {name} - {address_line_1} - {post_code} {city}."

                self.logger.debug(siae_info)

                if not dry_run:

                    siae = Siae()
                    siae.siret = siret
                    siae.naf = naf
                    siae.kind = Siae.KIND_GEIQ
                    siae.source = Siae.SOURCE_GEIQ
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

                        if (
                            not geocoding_data
                            or geocoding_data["score"] < API_BAN_RELIABLE_MIN_SCORE
                        ):
                            geocoding_data = get_geocoding_data(
                                siae.address_on_one_line,
                                post_code=f"{siae.post_code[:2]}000",
                            )

                        if (
                            not geocoding_data
                            or geocoding_data["score"] < API_BAN_RELIABLE_MIN_SCORE
                        ):
                            geocoding_data = get_geocoding_data(
                                siae.address_on_one_line
                            )

                        if (
                            not geocoding_data
                            or geocoding_data["score"] < API_BAN_RELIABLE_MIN_SCORE
                        ):
                            geocoding_data = get_geocoding_data(siae.address_line_1)

                        if (
                            not geocoding_data
                            or geocoding_data["score"] < API_BAN_RELIABLE_MIN_SCORE
                        ):
                            geocoding_data = get_geocoding_data(siae.address_line_2)

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
                            siae.city = geocoding_data["city"]
                        else:
                            self.stderr.write(
                                f"Geocoding not reliable for {siae_info}\n{siae.address_on_one_line}"
                            )

                        self.logger.debug("-" * 40)
                        self.logger.debug(siae.address_line_1)
                        self.logger.debug(siae.city)

                        siae.coords = geocoding_data["coords"]

                    siae.save()

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
