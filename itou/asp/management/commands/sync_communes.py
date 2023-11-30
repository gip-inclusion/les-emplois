import csv
import json
from datetime import datetime

from django.contrib.postgres.search import TrigramSimilarity
from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F, Q
from django.db.models.deletion import RestrictedError

from itou.asp.models import Commune
from itou.cities.models import City
from itou.users.models import JobSeekerProfile
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


def guess_commune(code, name, at=None):
    """Try and find the commune in the "new" attribution.
    For instance we might very well have communes that have the same name and code but the start_date has changed,
    making it "added" on one hand and "deleted" on the other. Find them.
    """
    extra_filters = []
    if at:
        extra_filters.append(Q(start_date__lte=at, end_date__gte=at) | Q(start_date__lte=at, end_date__isnull=True))
    return (
        Commune.objects.annotate(similarity=TrigramSimilarity("name", name))
        .filter(
            *extra_filters,
            code__startswith=code[:2],
            # in our tests, covering more than 50% of trigrams was enough to find similar names.
            similarity__gte=0.5,
        )
        .latest("similarity", F("end_date").asc(nulls_last=True))
    )


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
            ("code", "start_date"),
            Commune.objects.all(),
            ("code", "start_date"),
            [
                ("name", "name"),
                ("start_date", "start_date"),
                ("end_date", "end_date"),
            ],
        ):
            if item.kind == DiffItemKind.ADDITION or item.kind == DiffItemKind.EDITION:
                city = City.objects.filter(code_insee=item.raw["code"]).first()
                commune = Commune(
                    code=item.raw["code"],
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
                self.stdout.write(f"{item.label}\n")
            elif item.kind == DiffItemKind.DELETION:
                communes_removed_by_csv.add(item.db_obj.pk)
                data = {key: getattr(item.db_obj, key) for key in ("code", "name", "start_date", "end_date")}
                self.stdout.write(f"\tREMOVED {json.dumps(data, ensure_ascii=False, cls=DjangoJSONEncoder)}")

        if wet_run:
            with transaction.atomic():
                profiles_to_remap = []
                for pk in communes_removed_by_csv:
                    commune = Commune.objects.get(pk=pk)
                    try:
                        commune.delete()
                    except RestrictedError as exc:
                        for obj in exc.restricted_objects:
                            if obj.birth_place == commune:
                                obj.birth_place = None
                                setattr(obj, "_birth_place", (commune.code, commune.name))
                            if obj.hexa_commune == commune:
                                obj.hexa_commune = None
                                setattr(obj, "_hexa_commune", (commune.code, commune.name))
                            profiles_to_remap.append(obj)
                        JobSeekerProfile.objects.bulk_update(
                            exc.restricted_objects,
                            fields=["birth_place", "hexa_commune"],
                        )
                        commune.delete()
                self.stdout.write(f"> successfully deleted count={len(communes_removed_by_csv)} communes")

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

                objs = Commune.objects.bulk_create(communes_added_by_csv)
                self.stdout.write(f"> successfully created count={len(objs)} new communes")

                if profiles_to_remap:
                    has_raised = False
                    for profile in profiles_to_remap:
                        if old_commune_info := getattr(profile, "_birth_place", None):
                            try:
                                new_commune = guess_commune(
                                    *old_commune_info,
                                    profile.user.birthdate,
                                )
                                self.stdout.write(
                                    f"> REALIGN birth_place for code={old_commune_info[0]} "
                                    f"name={old_commune_info[1]} "
                                    f"at={profile.user.birthdate} "
                                    f"found with new_name={new_commune.name} "
                                    f"and start_date={new_commune.start_date}"
                                )
                            except Commune.DoesNotExist:
                                self.stdout.write(
                                    f"! new commune for code={old_commune_info[0]} "
                                    f"at={profile.user.birthdate} "
                                    f"name={old_commune_info[1]} not found ! Resolve manually."
                                )
                                has_raised = True
                            else:
                                profile.birth_place = new_commune

                        if old_commune_info := getattr(profile, "_hexa_commune", None):
                            try:
                                new_commune = guess_commune(*old_commune_info)
                                self.stdout.write(
                                    f"> REALIGN hexa_commune for code={old_commune_info[0]} "
                                    f"name={old_commune_info[1]} "
                                    f"found with new_name={new_commune.name} "
                                    f"and start_date={new_commune.start_date}"
                                )
                            except Commune.DoesNotExist:
                                self.stdout.write(
                                    f"! new commune for code={old_commune_info[0]} "
                                    f"name={old_commune_info[1]} not found ! Resolve manually."
                                )
                                has_raised = True
                            else:
                                profile.hexa_commune = new_commune

                    if has_raised:
                        raise Exception("Some communes could not be found. Please resolve manually.")

                    n_objs = JobSeekerProfile.objects.bulk_update(
                        profiles_to_remap,
                        fields=["birth_place", "hexa_commune"],
                    )
                    self.stdout.write(f"> realigned count={n_objs} JobSeeker profiles with updated communes.")
