import csv
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from itou.asp.models import Commune
from itou.cities.models import City
from itou.utils.sync import DiffItemKind, yield_sync_diff


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
    help = "Synchronizes communes with the latest CSV from the ASP and latest known Cities"

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
        communes_from_csv = list(csv_import_communes(file_path))

        communes_added_by_csv = []
        communes_updated_by_csv = []
        communes_removed_by_csv = set()

        for item in yield_sync_diff(
            communes_from_csv,
            "code",
            Commune.objects.all(),
            "code",
            [
                ("name", "name"),
                ("start_date", "start_date"),
                ("end_date", "end_date"),
            ],
        ):
            if item.kind == DiffItemKind.ADDITION or item.kind == DiffItemKind.EDITION:
                city = City.objects.filter(code_insee=item.key).first()
                commune = Commune(
                    code=item.key,
                    name=item.raw["name"],
                    start_date=item.raw["start_date"],
                    end_date=item.raw["end_date"],
                    city=city,  # all of the deactivated Communes will have None here.
                )
                if item.kind == DiffItemKind.EDITION:
                    commune.pk = item.db_obj.pk
                    communes_updated_by_csv.append(commune)
                elif item.kind == DiffItemKind.ADDITION:
                    communes_added_by_csv.append(commune)
            elif item.kind == DiffItemKind.DELETION:
                communes_removed_by_csv.add(item.key)

        if wet_run:
            with transaction.atomic():
                n_objs, _ = Commune.objects.filter(code__in=communes_removed_by_csv).delete()
                self.stdout.write(
                    f"> successfully deleted count={n_objs} communes insee_codes={sorted(communes_removed_by_csv)}"
                )

                objs = Commune.objects.bulk_create(communes_added_by_csv)
                self.stdout.write(f"> successfully created count={len(objs)} new communes")

                n_objs = Commune.objects.bulk_update(
                    communes_updated_by_csv,
                    fields=[
                        "code",
                        "name",
                        "start_date",
                        "end_date",
                        "city",
                    ],
                    batch_size=1000,
                )
                self.stdout.write(f"> successfully updated count={n_objs} communes")

        communes_without_cities_qs = Commune.objects.current().filter(city=None)
        self.stdout.write(f"> found {communes_without_cities_qs.count()} communes without city, will match again.")
        updated_communes_city = []
        for commune in communes_without_cities_qs:
            city = City.objects.filter(code_insee=commune.code).first()
            if city:
                commune.city = city
                updated_communes_city.append(commune)

        if wet_run:
            n_objs = Commune.objects.bulk_update(
                updated_communes_city,
                fields=[
                    "city",
                ],
                batch_size=1000,
            )
            self.stdout.write(f"> successfully updated count={n_objs} cities in preexisting communes")
