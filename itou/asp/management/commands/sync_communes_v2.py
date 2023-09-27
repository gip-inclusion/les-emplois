import csv
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from itou.asp.models import CommuneV2
from itou.cities.models import City


ASP_DATE_FORMAT = "%d/%m/%Y"


def csv_import_communes(filename):
    with open(filename, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)
        for line in reader:
            code = line[0]
            name = line[1]
            start_date = datetime.strptime(line[2], ASP_DATE_FORMAT).date() if line[2] else None
            end_date = datetime.strptime(line[3], ASP_DATE_FORMAT).date() if line[3] else None
            yield dict(code=code, name=name, start_date=start_date, end_date=end_date)


class Command(BaseCommand):
    help = "Synchronizes Communes 'V2' with the latest CSV from the ASP and latest known Cities"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Path of the ASP CSV file to import",
        )

    def handle(self, *, file_path, wet_run, **options):
        communes = []
        for commune in csv_import_communes(file_path):
            city = City.objects.filter(code_insee=commune["code"]).first()
            commune = CommuneV2(
                **commune,
                city=city,  # all of the deactivated Communes will have None here.
            )
            communes.append(commune)

        if wet_run:
            with transaction.atomic():
                objs = CommuneV2.objects.bulk_create(communes)
                self.stdout.write(f"> successfully created count={len(objs)} new communes")
