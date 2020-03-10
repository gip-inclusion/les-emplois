import json
import logging
import os

from django.core.management.base import BaseCommand

from itou.jobs.models import Appellation, Rome

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

JSON_FILE = f"{CURRENT_DIR}/data/appellations_for_romes.json"


class Command(BaseCommand):
    """
    Import ROMEs appellations into the database.

    To debug:
        django-admin import_appellations_for_romes --dry-run
        django-admin import_appellations_for_romes --dry-run --verbosity=2

    To populate the database:
        django-admin import_appellations_for_romes
    """

    help = "Import the content of the ROMEs appellations JSON file into the database."

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

        with open(JSON_FILE, "r") as raw_json_data:

            json_data = json.load(raw_json_data)
            total_len = len(json_data)
            last_progress = 0

            for i, item in enumerate(json_data):

                progress = int((100 * i) / total_len)
                if progress > last_progress + 5:
                    self.stdout.write(f"Creating job's appellations… {progress}%")
                    last_progress = progress

                code_rome = item

                rome = Rome.objects.get(code=code_rome)

                appellations_for_rome = json_data[code_rome]

                self.logger.debug("-" * 80)
                self.logger.debug(code_rome)

                for appellation in appellations_for_rome:

                    code = appellation["code"]
                    # There are 2 names: item['libelle'] and item['libelleCourt'].
                    # The difference is unclear and the data seems to be about the same.
                    # We keep only item['libelleCourt'] to stay as simple as possible.
                    name = appellation["libelleCourt"]

                    self.logger.debug(code)
                    self.logger.debug(name)

                    if not dry_run:
                        Appellation.objects.update_or_create(
                            code=code, defaults={"name": name, "rome": rome}
                        )

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
