import json
import urllib.parse

import httpx
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.template.defaultfilters import slugify
from django.utils import timezone

from itou.cities.models import City, EditionModeChoices
from itou.common_apps.address.models import AddressMixin
from itou.companies.models import JobDescription
from itou.utils.command import BaseCommand, dry_runnable
from itou.utils.sync import DiffItemKind, yield_sync_diff


# TODO(xfernandez): drop this default when the field will be non-nullable
DEFAULT_LAST_SYNCED_AT = "2020-01-01"


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


def get_next_insee_code(previous_insee_code, date):
    next_communes = (
        httpx.get(
            urllib.parse.urljoin(
                settings.API_INSEE_METADATA_URL,
                f"geo/commune/{previous_insee_code}/suivants",
            ),
            params={"date": date},
            headers={"Accept": "application/json"},
        )
        .raise_for_status()
        .json()
    )
    if len(next_communes) != 1:
        # If there is several following communes, we cannot decide which one to pick.
        # If there is none (which shouldn't happen), we cannot either.
        return None
    next_commune = next_communes[0]
    if next_commune.get("dateSuppression"):
        # If the next commune is itself suppressed, we need to go further.
        return get_next_insee_code(previous_insee_code, date=next_commune["dateCreation"])
    return next_commune["code"]


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

    def handle_deletions(self, cities_removed_by_api):
        relations_to_fix = [
            (JobDescription, "location"),
            *((model, "insee_city") for model in AddressMixin.__subclasses__()),
        ]
        model_to_refill_infos = {}
        for model, field_name in relations_to_fix:
            refill_infos = {
                pk: (previous_insee_code, last_synced_at)
                for pk, previous_insee_code, last_synced_at in model.objects.filter(
                    **{f"{field_name}__code_insee__in": cities_removed_by_api}
                ).values_list("pk", f"{field_name}__code_insee", f"{field_name}__last_synced_at")
            }
            model.objects.filter(pk__in=refill_infos).update(**{field_name: None})
            self.logger.info(
                f"Removed {field_name} from count=%d {model.__name__} due to city deletion", len(refill_infos)
            )
            model_to_refill_infos[model] = refill_infos

        n_objs, _ = City.objects.filter(code_insee__in=cities_removed_by_api).delete()
        return n_objs, model_to_refill_infos

    def handle_refill_of_deleted_cities(self, model_to_refill_infos):
        previous_insee_infos = set(
            previous_city_infos
            for refill_infos in model_to_refill_infos.values()
            for previous_city_infos in refill_infos.values()
        )
        self.logger.info("count=%d cities to replace", len(previous_insee_infos))

        if not previous_insee_infos:
            # Nothing to do
            return

        replacement_cities = {}
        for previous_insee_code, last_synced_at in previous_insee_infos:
            new_insee_code = get_next_insee_code(
                previous_insee_code,
                date=timezone.localdate(last_synced_at).isoformat() if last_synced_at else DEFAULT_LAST_SYNCED_AT,
            )
            if new_insee_code:
                new_city = City.objects.get(code_insee=new_insee_code)  # It should exist
                replacement_cities[previous_insee_code] = new_city
            else:
                self.logger.error(
                    "Could not find replacement city for previous_insee_code=%s (last_synced_at=%s)",
                    previous_insee_code,
                    last_synced_at,
                )
        self.logger.info("Found count=%d replacements", len(replacement_cities))
        for model, pk_to_previous_infos in model_to_refill_infos.items():
            fixable_instances = []
            field_name = "location" if model is JobDescription else "insee_city"
            for model_instance in model.objects.filter(pk__in=pk_to_previous_infos):
                previous_insee_code = pk_to_previous_infos[model_instance.pk][0]
                if new_city := replacement_cities.get(previous_insee_code):
                    setattr(model_instance, field_name, new_city)
                    fixable_instances.append(model_instance)
                    self.logger.info(
                        f"Refilled {model.__name__}.{field_name} for pk=%s to city=%d (previous=%s)",
                        model_instance.pk,
                        new_city.pk,
                        previous_insee_code,
                    )
                else:
                    self.logger.warning(
                        f"Could not refill {model.__name__}.{field_name} for pk=%d (previous=%s)",
                        model_instance.pk,
                        previous_insee_code,
                    )
            model.objects.bulk_update(fixable_instances, fields=[field_name], batch_size=1000)
            self.logger.info(f"successfully refilled count=%d new cities for {model.__name__}", len(fixable_instances))

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

        # model_to_refill_infos is a dict of {ModelClass: {instance_pk: (previous_insee_code, last_synced_at)}}
        n_objs, model_to_refill_infos = self.handle_deletions(cities_removed_by_api)
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

        # Try to refill deleted cities
        self.handle_refill_of_deleted_cities(model_to_refill_infos)
