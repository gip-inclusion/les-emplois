import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from itou.siae.models import Siae


# This is temporary data. We must find a better source.
# This file contains data manually fixed and exported from:
# https://docs.google.com/spreadsheets/d/1E9HSpcypZXK4MieYjQzjHXXcQWPbTJyK0r5kWD8jIjg/#gid=1808034083
CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
CSV_FILE = f"{CURRENT_DIR}/data/siae67.csv"


class Command(BaseCommand):
    """
    Import SIAEs data into the database.

    To debug:
    make django_admin COMMAND="import_siae67 --dry-run"

    To populate the database:
    make django_admin COMMAND=import_siae67
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

                siret = row[6].strip().replace(' ', '')
                siret = ' '.join(siret.split())
                self.stdout.write(siret)
                assert len(siret) == 14

                kind = row[0]
                self.stdout.write(kind)

                name = row[1].strip().lower().title()
                name = ' '.join(name.split())
                self.stdout.write(name)

                activities = row[2].strip()
                activities = ' '.join(activities.split())
                self.stdout.write(activities)

                address = row[3].strip().replace('-', ' - ').replace('\n ', ' - ')
                address = ' '.join(address.split())
                self.stdout.write(address)

                phone = row[4].strip()
                phone = ' '.join(phone.split())
                self.stdout.write(phone)
                assert len(phone) == 14

                email = row[5].strip()
                self.stdout.write(email)

                if not dry_run:
                    siae = Siae()
                    siae.siret = siret
                    siae.kind = kind
                    siae.name = name
                    siae.activities = activities
                    siae.address = address
                    siae.phone = phone
                    siae.email = email
                    siae.save()

        self.stdout.write('-' * 80)
        self.stdout.write("Done.")
