import json
import logging
import os

from django.core.management.base import BaseCommand

from itou.jobs.models import Rome

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

JSON_FILE = f"{CURRENT_DIR}/data/romes.json"


class Command(BaseCommand):
    """
    Import ROMEs into the database.

    To debug:
        django-admin import_romes --dry-run
        django-admin import_romes --dry-run --verbosity=2

    To populate the database:
        django-admin import_romes
    """

    help = "Import the content of the ROMEs JSON file into the database."

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

            RIASEC_DICT = dict(Rome.RIASEC_CHOICES)

            for i, item in enumerate(json_data):

                progress = int((100 * i) / total_len)
                if progress > last_progress + 5:
                    self.stdout.write(f"Creating ROME appellations… {progress}%")
                    last_progress = progress

                code = item["code"]
                name = item["libelle"]
                riasec_major = item["riasecMajeur"]
                riasec_minor = item["riasecMineur"]
                code_isco = item["codeIsco"]

                # Skipping domain for now.
                # domaine_name = item['domaineProfessionnel']['libelle']
                # domaine_code = item['domaineProfessionnel']['code']
                # broad_domain_name = item['domaineProfessionnel']['grandDomaine']['libelle']
                # broad_domain_code = item['domaineProfessionnel']['grandDomaine']['code']

                self.logger.debug("-" * 80)
                self.logger.debug(code)
                self.logger.debug(name)
                self.logger.debug(RIASEC_DICT[riasec_major])
                self.logger.debug(RIASEC_DICT[riasec_minor])
                self.logger.debug(code_isco)

                if not dry_run:
                    Rome.objects.update_or_create(
                        code=code,
                        defaults={
                            "name": name,
                            "riasec_major": riasec_major,
                            "riasec_minor": riasec_minor,
                            "code_isco": code_isco,
                        },
                    )

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
