import json
import urllib.parse

import httpx
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from django.template.defaultfilters import slugify

from itou.cities.models import City, EditionModeChoices
from itou.utils.command import BaseCommand
from itou.utils.sync import DiffItemKind, yield_sync_diff


def strip_arrondissement(raw_city):
    raw_city["nom"] = raw_city["nom"].replace("Arrondissement", "").strip()
    return raw_city


def fetch_cities(districts_only=False):
    params = {
        "fields": "nom,code,codesPostaux,codeDepartement,codeRegion,centre",
        "format": "json",
    }
    if districts_only:
        params["type"] = "arrondissement-municipal"
    response = httpx.get(urllib.parse.urljoin(settings.API_GEO_BASE_URL, f"communes?{urllib.parse.urlencode(params)}"))
    response.raise_for_status()
    answer = response.json()
    if districts_only:
        answer = [strip_arrondissement(raw_city) for raw_city in answer]
    return answer


def point_from_api_data(obj):
    return GEOSGeometry(json.dumps(obj["centre"]))


def api_city_to_db_city(data):
    name = data["nom"]
    department = data["codeDepartement"]
    return City(
        name=name,
        slug=slugify(f"{name}-{department}"),
        department=department,
        post_codes=sorted(data["codesPostaux"]),
        code_insee=data["code"],
        coords=point_from_api_data(data),
        edition_mode=EditionModeChoices.AUTO,
    )


class Command(BaseCommand):
    help = "Synchronizes cities with the GEO API"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        cities_from_api = fetch_cities() + fetch_cities(districts_only=True)

        cities_added_by_api = []
        cities_updated_by_api = []
        cities_removed_by_api = set()

        for item in yield_sync_diff(
            cities_from_api,
            "code",
            City.objects.all(),
            "code_insee",
            [
                ("nom", "name"),
                ("codeDepartement", "department"),
                (lambda obj: sorted(obj["codesPostaux"]), "post_codes"),
                (point_from_api_data, "coords"),
            ],
        ):
            if item.kind == DiffItemKind.ADDITION:
                cities_added_by_api.append(api_city_to_db_city(item.raw))
            elif item.kind == DiffItemKind.EDITION:
                db_city = item.db_obj
                if db_city.edition_mode != EditionModeChoices.AUTO:
                    self.stdout.write(f"! skipping manually edited city={db_city} from update")
                    continue
                city = api_city_to_db_city(item.raw)
                city.pk = db_city.pk
                cities_updated_by_api.append(city)
            elif item.kind == DiffItemKind.DELETION:
                cities_removed_by_api.add(item.key)
            self.stdout.write(item.label)

        if wet_run:
            with transaction.atomic():
                # Note: for now we'll let the cron remove the cities since there is very little chance that
                # a City that is linked to one of our JobDescriptions would suddenly disappear. Handle that
                # case as it happens, by "deactivating" the city by instance: the cron would crash.
                n_objs, _ = City.objects.filter(code_insee__in=cities_removed_by_api).delete()
                self.stdout.write(f"> successfully deleted count={n_objs} cities insee_codes={cities_removed_by_api}")

                objs = City.objects.bulk_create(cities_added_by_api)
                self.stdout.write(f"> successfully created count={len(objs)} new cities")

                n_objs = City.objects.bulk_update(
                    cities_updated_by_api,
                    fields=[
                        "name",
                        "slug",
                        "department",
                        "post_codes",
                        "code_insee",
                        "coords",
                    ],
                    batch_size=1000,
                )
                self.stdout.write(f"> successfully updated count={n_objs} cities")
