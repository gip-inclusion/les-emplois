import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from itou.utils.apis.pole_emploi_connect import get_access_token

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


class Command(BaseCommand):
    """
    Creates a JSON file with all ROMEs.
    The data source is a JSON file that comes from Pôle emploi's ROME API.

    To generate the file:
        django-admin generate_romes
    """

    help = "Create a JSON file with all ROMEs."

    def handle(self, **options):

        token = get_access_token("api_romev1 nomenclatureRome")
        url = f"{settings.API_EMPLOI_STORE_BASE_URL}/rome/v1/metier"
        r = requests.get(url, headers={"Authorization": token})
        r.raise_for_status()

        file_path = f"{CURRENT_DIR}/data/romes.json"
        with open(file_path, "wb") as f:
            f.write(r.content)

        self.stdout.write("-" * 80)
        self.stdout.write(f"File available at `{file_path}`.")
        self.stdout.write("Done.")
