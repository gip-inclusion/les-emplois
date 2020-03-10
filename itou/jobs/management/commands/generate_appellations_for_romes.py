import json
import os
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from itou.utils.apis.pole_emploi_connect import get_access_token

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

JSON_FILE = f"{CURRENT_DIR}/data/romes.json"


class Command(BaseCommand):
    """
    Creates a JSON file with all appellations for ROME codes.
    The data source is a JSON file that comes from Pôle emploi's ROME API.

    To generate the file:
        django-admin generate_appellations_for_romes
    """

    help = "Create a JSON file with all appellations for ROME codes."

    def handle(self, **options):

        result = {}

        with open(JSON_FILE, "r") as raw_json_data:

            json_data = json.load(raw_json_data)
            total_len = len(json_data)
            last_progress = 0

            for i, item in enumerate(json_data):

                progress = int((100 * i) / total_len)
                if progress > last_progress + 5:
                    self.stdout.write(
                        f"Creating appellations for ROME codes… {progress}%"
                    )
                    last_progress = progress

                rome_code = item["code"]

                self.stdout.write(f"Processing {rome_code}")

                token = get_access_token("api_romev1 nomenclatureRome")
                url = f"{settings.API_EMPLOI_STORE_BASE_URL}/rome/v1/metier/{rome_code}/appellation"
                r = requests.get(url, headers={"Authorization": token})
                r.raise_for_status()

                result[rome_code] = r.json()

                # Rate limiting is killing me.
                # We can't go down below 4 seconds without getting an error 429 "Too Many Requests".
                # Fetching this data is slow and can take between 35 to 40 min.
                time.sleep(4)

        file_path = f"{CURRENT_DIR}/data/appellations_for_rome.json"
        with open(file_path, "w") as f:
            json.dump(result, f)

        self.stdout.write("-" * 80)
        self.stdout.write(f"File available at `{file_path}`.")
        self.stdout.write("Done.")
