import json
import os

import requests

from django.conf import settings
from django.core.management.base import BaseCommand


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


class Command(BaseCommand):
    """
    This command will create a JSON file with all cities of France.
    The data source is a JSON file that comes from api.gouv.fr's GeoAPI.

    To generate the file:
        django-admin generate_cities_file
    """
    help = "Create a JSON file with all cities of France."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            help='Only print data to import',
        )

    def handle(self, dry_run=False, **options):

        base_url = f"{settings.API_GEO_BASE_URL}/communes"
        fields = "?fields=nom,code,codesPostaux,codeDepartement,codeRegion,centre"
        extra = "&format=json"
        url = f"{base_url}{fields}{extra}"

        r = requests.get(url)

        file_path = f"{CURRENT_DIR}/data/cities.json"
        with open(file_path, 'wb') as f:
            f.write(r.content)

        self.stdout.write('-' * 80)
        self.stdout.write(f"File available at `{file_path}`.")
        self.stdout.write("Done.")
