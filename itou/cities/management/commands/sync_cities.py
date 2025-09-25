import json
import urllib.parse

import httpx
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.template.defaultfilters import slugify
from django.utils import timezone

from itou.cities.models import City, EditionModeChoices
from itou.utils.command import BaseCommand, dry_runnable
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
    answer = (
        httpx.get(urllib.parse.urljoin(settings.API_GEO_BASE_URL, f"communes?{urllib.parse.urlencode(params)}"))
        .raise_for_status()
        .json()
    )
    if districts_only:
        answer = [strip_arrondissement(raw_city) for raw_city in answer]
    return answer


def point_from_api_data(obj):
    return GEOSGeometry(json.dumps(obj["centre"]))


def api_city_to_db_city(data, last_synced_at):
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
        last_synced_at=last_synced_at,
    )


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = "Synchronizes cities with the GEO API"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        cities_from_api = fetch_cities() + fetch_cities(districts_only=True)
        last_synced_at = timezone.now()

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
                cities_added_by_api.append(api_city_to_db_city(item.raw, last_synced_at))
            elif item.kind == DiffItemKind.EDITION:
                db_city = item.db_obj
                if db_city.edition_mode != EditionModeChoices.AUTO:
                    self.logger.warning("skipping manually edited city=%s from update", db_city)
                    continue
                city = api_city_to_db_city(item.raw, last_synced_at)
                city.pk = db_city.pk
                cities_updated_by_api.append(city)
            elif item.kind == DiffItemKind.DELETION:
                cities_removed_by_api.add(item.key)
            self.logger.info(item.label)

        # Note: for now we'll let the cron remove the cities since there is very little chance that
        # a City that is linked to one of our JobDescriptions would suddenly disappear. Handle that
        # case as it happens, by "deactivating" the city by instance: the cron would crash.
        n_objs, _ = City.objects.filter(code_insee__in=cities_removed_by_api).delete()
        self.logger.info("successfully deleted count=%d cities insee_codes=%s", n_objs, sorted(cities_removed_by_api))

        n_objs = City.objects.bulk_update(
            cities_updated_by_api,
            fields=[
                "name",
                "slug",
                "department",
                "post_codes",
                "code_insee",
                "coords",
                "last_synced_at",
            ],
            batch_size=1000,
        )
        self.logger.info("successfully updated count=%d cities", n_objs)

        objs = City.objects.bulk_create(cities_added_by_api)
        self.logger.info("successfully created count=%d new cities", len(objs))
