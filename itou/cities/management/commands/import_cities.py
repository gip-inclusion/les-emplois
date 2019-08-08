import json
import logging
import os

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from django.template.defaultfilters import slugify

from itou.utils.address.departments import DEPARTMENTS
from itou.cities.models import City


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CITIES_JSON_FILE = f"{CURRENT_DIR}/data/cities.json"


class Command(BaseCommand):
    """
    Import French cities data into the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_cities --dry-run
        django-admin import_cities --dry-run --verbosity=2

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

        self.set_logger(options.get('verbosity'))

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

                self.logger.debug('-' * 80)
                self.logger.debug(name)
                self.logger.debug(department)
                self.logger.debug(post_codes)
                self.logger.debug(code_insee)
                self.logger.debug(longitude)
                self.logger.debug(latitude)

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
                        self.logger.debug(created)

        self.stdout.write('-' * 80)
        self.stdout.write("Done.")
