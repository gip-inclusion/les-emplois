import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


class Command(BaseCommand):
    """
    Creates a JSON file with all cities of France.
    The data source is a JSON file that comes from api.gouv.fr's GeoAPI.

    It can be run from time to time (every year) to get updated data that
    can be imported via `django-admin import_cities`.

    To generate the file:
        django-admin generate_cities
    """

    help = "Create a JSON file with all cities of France."

    def handle(self, **options):

        base_url = f"{settings.API_GEO_BASE_URL}/communes"
        fields = "?fields=nom,code,codesPostaux,codeDepartement,codeRegion,centre"
        extra = "&format=json"
        url = f"{base_url}{fields}{extra}"

        r = requests.get(url)

        file_path = f"{CURRENT_DIR}/data/cities.json"
        with open(file_path, "wb") as f:
            f.write(r.content)

        self.stdout.write("-" * 80)
        self.stdout.write(f"File available at `{file_path}`.")
        self.stdout.write("Done.")
