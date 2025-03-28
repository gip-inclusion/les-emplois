import pprint
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from itou.metabase.models import DatumKey
from itou.users.models import JobSeekerProfile
from itou.utils.apis.metabase import DEPARTMENT_FILTER_KEY, REGION_FILTER_KEY, Client
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    CACHE_NAME = "stats"

    KPI_TO_FETCH = {
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
        subparsers = parser.add_subparsers(dest="data", required=True)

        kpi = subparsers.add_parser("kpi")
        kpi.add_argument("action", choices=["fetch", "show"])
        kpi.add_argument("--wet-run", dest="wet_run", action="store_true")

        stalled_job_seekers = subparsers.add_parser("stalled-job-seekers")
        stalled_job_seekers.add_argument("--wet-run", dest="wet_run", action="store_true")

    def fetch_kpi(self, *, wet_run):
        cache = caches[self.CACHE_NAME]
        client = Client(settings.METABASE_SITE_URL)

        metabase_data = {DatumKey.DATA_UPDATED_AT: timezone.now()}
        for datum_key, metabase_informations in self.KPI_TO_FETCH.items():
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

    def show_kpi(self, *, wet_run):
        data = caches[self.CACHE_NAME].get_many(DatumKey)
        for key, value in data.items():
            print(repr(key))
            print(repr(value))
            print()

    @transaction.atomic()
    def fetch_stalled_job_seekers(self, *, wet_run):
        client = Client(settings.METABASE_SITE_URL)

        currently_stalled_job_seeker_ids = {row["ID"] for row in client.fetch_card_results(4412, fields=[54509])}
        self.logger.info("Number of stalled job seekers: %d", len(currently_stalled_job_seeker_ids))

        db_stalled_job_seeker_ids = set(
            JobSeekerProfile.objects.filter(is_stalled=True).values_list("user_id", flat=True)
        )
        self.logger.info("Number of stalled job seekers in database: %d", len(db_stalled_job_seeker_ids))

        exiting_stalled_status_ids = db_stalled_job_seeker_ids - currently_stalled_job_seeker_ids
        self.logger.info("Number of job seekers exiting stalled status: %d", len(exiting_stalled_status_ids))
        entering_stalled_status_ids = currently_stalled_job_seeker_ids - db_stalled_job_seeker_ids
        self.logger.info("Number of job seekers entering stalled status: %d", len(entering_stalled_status_ids))

        if wet_run:
            exiting_update_count = JobSeekerProfile.objects.filter(
                is_stalled=True, pk__in=exiting_stalled_status_ids
            ).update(is_stalled=False)
            entering_update_count = JobSeekerProfile.objects.filter(
                is_stalled=False, pk__in=entering_stalled_status_ids
            ).update(is_stalled=True)
            self.logger.info(
                "Number of job seekers updated: exiting=%d entering=%d", exiting_update_count, entering_update_count
            )

    def handle(self, *, data, **options):
        match data:
            case "kpi":
                action_function = {
                    "fetch": self.fetch_kpi,
                    "show": self.show_kpi,
                }[options["action"]]
                action_function(wet_run=options["wet_run"])
            case "stalled-job-seekers":
                self.fetch_stalled_job_seekers(wet_run=options["wet_run"])
