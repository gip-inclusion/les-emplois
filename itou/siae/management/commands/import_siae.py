import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from itou.siae.models import Siae
from itou.utils.address.departments import DEPARTMENTS
from itou.utils.geocoding import get_geocoding_data


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

# This file resides outside the repository until approval for public release has been given.
CSV_FILE = f"{CURRENT_DIR}/data/2019_07_liste_siae.csv"

KINDS = dict(Siae.KIND_CHOICES).keys()


class Command(BaseCommand):
    """
    Import SIAEs data into the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_siae --dry-run

    To populate the database:
        django-admin import_siae
    """
    help = "Import the content of the SIAE csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            help='Only print data to import',
        )

    def handle(self, dry_run=False, **options):

        with open(CSV_FILE) as csvfile:

            reader = csv.reader(csvfile, delimiter=';')

            for i, row in enumerate(reader):

                if i == 0:
                    # Skip CSV header.
                    continue

                self.stdout.write('-' * 80)

                siret = row[7]
                self.stdout.write(siret)
                assert len(siret) == 14

                naf = row[5]
                self.stdout.write(naf)
                assert len(naf) == 5

                kind = row[0]
                self.stdout.write(kind)
                assert kind in KINDS

                # Max length of `name` is 50 chars in the source file, some are truncated.
                # Also `name` is in upper case.
                name = row[8].strip()
                name = ' '.join(name.split())  # Replace multiple spaces by a single space.
                self.stdout.write(name)

                phone = row[13].strip().replace(' ', '')
                if phone and len(phone) != 10:
                    phone = ''
                if phone:
                    self.stdout.write(phone)

                email = row[14].strip()
                self.stdout.write(email)
                assert ' ' not in email

                street_num = row[9].strip().replace(' ', '')
                street_name = row[10].strip().lower()
                street_name = ' '.join(street_name.split())  # Replace multiple spaces by a single space.
                address_line_1 = f"{street_num} {street_name}"
                address_line_1 = ' '.join(address_line_1.split())  # Replace multiple spaces by a single space.
                address_line_2 = ''
                if ' - ' in address_line_1:
                    addresses = address_line_1.split(' - ')
                    address_line_1 = addresses[0]
                    address_line_2 = addresses[1]
                self.stdout.write(address_line_1)
                if address_line_2:
                    self.stdout.write(address_line_2)

                # Fields are identical, we can use one or another.
                zipcode = row[3].strip()
                post_code = row[11].strip()
                self.stdout.write(zipcode)
                assert post_code == zipcode

                # Fields are identical, we can use one or another.
                city = row[4].strip()
                city_name = row[12].strip()
                self.stdout.write(city)
                assert city_name == city

                department = row[1]
                if department[0] == '0':
                    department = department[1:]
                if department in ['59L', '59V']:
                    department = '59'
                self.stdout.write(department)
                assert department in DEPARTMENTS

                if not dry_run:

                    siae = Siae()
                    siae.siret = siret
                    siae.naf = naf
                    siae.kind = kind
                    siae.name = name
                    siae.phone = phone
                    siae.email = email
                    siae.address_line_1 = address_line_1
                    siae.address_line_2 = address_line_2
                    siae.zipcode = zipcode
                    siae.city = city
                    siae.department = department

                    if siae.address_on_one_line:

                        geocoding_data = get_geocoding_data(siae.address_on_one_line, zipcode=siae.zipcode)

                        if not geocoding_data:
                            siae.save()
                            continue

                        siae.geocoding_score = geocoding_data['score']
                        # If the score is high enough, use the address name returned by the BAN API
                        # because it's better written using accents etc. VS source data in all caps.
                        # Otherwise keep the old address (which is probably wrong or incomplete).
                        if siae.geocoding_score >= siae.API_BAN_RELIABLE_MIN_SCORE:
                            siae.address_line_1 = geocoding_data['address_line_1']
                        # City is always good due to `postcode` passed in query.
                        # ST MAURICE DE REMENS => Saint-Maurice-de-Rémens
                        siae.city = geocoding_data['city']

                        self.stdout.write('-' * 40)
                        self.stdout.write(siae.address_line_1)
                        self.stdout.write(siae.city)

                        siae.coords = geocoding_data['coords']

                    siae.save()

        self.stdout.write('-' * 80)
        self.stdout.write("Done.")
