import pprint
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from itou.metabase.models import DatumKey
from itou.utils.apis.metabase import DEPARTMENT_FILTER_KEY, REGION_FILTER_KEY, Client
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    CACHE_NAME = "stats"

    DATA_TO_FETCH = {
        DatumKey.FLUX_IAE_DATA_UPDATED_AT: {
            "card_id": 272,
            "converter": parse_datetime,
            "select": "Date Mise À Jour Metabase",
        },
        DatumKey.JOB_SEEKER_STILL_SEEKING_AFTER_30_DAYS: {
            "card_id": 4413,
            "select": "Valeurs distinctes de ID",
            "group_by": {
                # Not totally sure why but for this one we can use the field name instead of the field id.
                "department": (unquote(DEPARTMENT_FILTER_KEY), "Département"),
                "region": (unquote(REGION_FILTER_KEY), "Région"),
            },
        },
        DatumKey.JOB_APPLICATION_WITH_HIRING_DIFFICULTY: {
            "card_id": 1175,
            "select": "Nombre de fiches de poste en difficulté de recrutement",
            "group_by": {
                "department": (10385, "Département Structure"),
                "region": (13680, "Région Structure"),
            },
            "filters": {
                29222: ["IAE"],
            },
        },
        DatumKey.RATE_OF_AUTO_PRESCRIPTION: {
            "card_id": 5292,
            "select": "% embauches en auto-prescription",
            "group_by": {
                "department": (17675, "Département Structure"),
                "region": (17676, "Région Structure"),
            },
        },
    }

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("action", choices=["fetch", "show"])
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def fetch(self, *, wet_run):
        cache = caches[self.CACHE_NAME]
        client = Client(settings.METABASE_SITE_URL)

        metabase_data = {DatumKey.DATA_UPDATED_AT: timezone.now()}
        for datum_key, metabase_informations in self.DATA_TO_FETCH.items():
            self.logger.info("Fetching datum_key=%s", datum_key)
            converter = metabase_informations.get("converter", lambda x: x)
            filters = metabase_informations.get("filters")

            # Fetch the base data
            results = client.fetch_card_results(metabase_informations["card_id"], filters=filters)
            metabase_data[datum_key] = converter(results[0][metabase_informations["select"]])

            # Fetch the "group_by" data
            for name, (field, column_name) in metabase_informations.get("group_by", {}).items():
                self.logger.info("Fetching datum_key=%s group_by=%s", datum_key, name)
                results = client.fetch_card_results(
                    metabase_informations["card_id"],
                    filters=filters,
                    group_by=[field],
                )
                metabase_data[datum_key.grouped_by(name)] = {
                    row[column_name]: converter(row[metabase_informations["select"]]) for row in results
                }

        if wet_run:
            self.logger.info("Saving data into cache %r", self.CACHE_NAME)
            cache.set_many(metabase_data)
        else:
            pprint.pp(metabase_data, sort_dicts=True)

    def show(self, *, wet_run):
        data = caches[self.CACHE_NAME].get_many(DatumKey)
        for key, value in data.items():
            print(repr(key))
            print(repr(value))
            print()

    def handle(self, action, *, wet_run, **kwargs):
        getattr(self, action)(wet_run=wet_run)
