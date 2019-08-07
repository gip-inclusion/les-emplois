import json
import os

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from django.template.defaultfilters import slugify

from itou.utils.address.departments import DEPARTMENTS
from itou.utils.cities.models import City


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CITIES_JSON_FILE = f"{CURRENT_DIR}/data/cities.json"


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

        with open(CITIES_JSON_FILE, 'r') as raw_json_data:

            json_data = json.load(raw_json_data)
            total_len = len(json_data)
            last_progress = 0

            for i, item in enumerate(json_data):

                progress = int((100 * i) / total_len)
                if progress > last_progress + 5:
                    self.stdout.write(f"Creating cities… {progress}%")
                    last_progress = progress

                name = item['nom']
                department = item.get('codeDepartement')
                if department:
                    assert department in DEPARTMENTS
                post_codes = item['codesPostaux']
                code_insee = item['code']
                centre = item.get('centre')
                if not centre:
                    self.stderr.write(f"No coordinates for {name}. Skipping…")
                    continue
                longitude = centre['coordinates'][0]
                latitude = centre['coordinates'][1]

                if dry_run:
                    print('-' * 80)
                    print(name)
                    print(department)
                    print(post_codes)
                    print(code_insee)
                    print(longitude)
                    print(latitude)

                if not dry_run:
                    _, created = City.objects.update_or_create(
                        slug=slugify(name),
                        department=department,
                        defaults={
                            'name': name,
                            'post_codes': post_codes,
                            'code_insee': code_insee,
                            'coords': GEOSGeometry(f"POINT({longitude} {latitude})"),
                        },
                    )
                    if created:
                        print(created)

        self.stdout.write('-' * 80)
        self.stdout.write("Done.")
