import csv
import os

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand

from itou.utils.cities.models import City


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

# https://sql.sh/736-base-donnees-villes-francaises
CSV_FILE = f"{CURRENT_DIR}/data/villes_france.csv"


class Command(BaseCommand):
    """
    Import French cities data into the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_cities --dry-run

    To populate the database:
        django-admin import_cities
    """
    help = "Import the content of the French cities csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            help='Only print data to import',
        )

    def handle(self, dry_run=False, **options):

        with open(CSV_FILE) as csvfile:

            reader = csv.reader(csvfile, delimiter=',')

            for i, row in enumerate(reader):

                name = row[5]
                department = row[1]
                post_codes = row[8].split('-')
                code_insee = row[10]
                longitude = row[19]
                latitude = row[20]

                if dry_run:
                    self.stdout.write('-' * 80)
                    self.stdout.write(name)
                    self.stdout.write(department)
                    self.stdout.write(str(post_codes))
                    self.stdout.write(code_insee)

                if not dry_run:
                    city = City()
                    city.name = name
                    city.department = department
                    city.post_codes = post_codes
                    city.code_insee = code_insee
                    city.coords = GEOSGeometry(f"POINT({longitude} {latitude})")
                    city.save()

        self.stdout.write('-' * 80)
        self.stdout.write("Done.")
