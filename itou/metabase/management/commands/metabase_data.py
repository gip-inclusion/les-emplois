import pprint
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from itou.companies.models import Contract
from itou.metabase.models import DatumKey
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis.metabase import DEPARTMENT_FILTER_KEY, REGION_FILTER_KEY, Client
from itou.utils.command import BaseCommand, dry_runnable


class Command(BaseCommand):
    ATOMIC_HANDLE = True

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

        riae_contracts = subparsers.add_parser("riae-contracts")
        riae_contracts.add_argument("--wet-run", dest="wet_run", action="store_true")

    def fetch_kpi(self):
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

        pprint.pp(metabase_data, sort_dicts=True)

        def save_kpi():
            self.logger.info("Saving data into cache %r", self.CACHE_NAME)
            cache.set_many(metabase_data)

        transaction.on_commit(save_kpi)

    def show_kpi(self):
        data = caches[self.CACHE_NAME].get_many(DatumKey)
        for key, value in data.items():
            print(repr(key))
            print(repr(value))
            print()

    def fetch_stalled_job_seekers(self):
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

        exiting_update_count = JobSeekerProfile.objects.filter(
            is_stalled=True, pk__in=exiting_stalled_status_ids
        ).update(is_stalled=False)
        entering_update_count = JobSeekerProfile.objects.filter(
            is_stalled=False, pk__in=entering_stalled_status_ids
        ).update(is_stalled=True)
        converging_update_count = JobSeekerProfile.objects.filter(is_stalled=~F("is_not_stalled_anymore")).update(
            is_not_stalled_anymore=None
        )
        self.logger.info(
            "Number of job seekers updated: exiting=%d entering=%d converging=%s",
            exiting_update_count,
            entering_update_count,
            converging_update_count,
        )

    def _get_riae_contracts_data(self):
        client = Client(settings.METABASE_SITE_URL)
        QUERY_LIMIT = 100_000  # Limit to <10MB data in ram (estimated with pympler.asizeof.asizeof)

        # Schema:
        # [{'Contrat Date Embauche': '2023-01-01',
        #   'Contrat Date Fin Contrat': '2023-04-30',
        #   'Contrat Date Sortie Definitive': None,
        #   'Contrat ID Ctr': ##########,
        #   'Contrat ID Structure': ###,
        #   'Contrat Mesure Disp Code': 'ACI_DC',
        #   'Contrat Parent ID': ##########,
        #   'Emplois Candidat ID': ##,
        #   'Type Contrat': 'initial'}]
        base_query = client.build_query(
            table=2150,
            order_by=[
                62289,  # Emplois Candidat ID
                62288,  # Contrat Parent ID
                61917,  # Contrat ID Ctr
            ],
            limit=QUERY_LIMIT,
        )

        contracts = client.fetch_dataset_results(client.build_dataset_query(database=2, query=base_query))

        while contracts:
            yield from contracts

            query = client.merge_query(
                into=base_query,
                query={
                    "filter": [
                        "or",
                        [
                            "and",
                            [
                                "=",
                                ["field", 62289, {"base-type": "type/Integer"}],
                                contracts[-1]["Emplois Candidat ID"],
                            ],
                            [
                                ">=",
                                ["field", 62288, {"base-type": "type/BigInteger"}],
                                contracts[-1]["Contrat Parent ID"],
                            ],
                            [
                                ">",
                                ["field", 61917, {"base-type": "type/BigInteger"}],
                                contracts[-1]["Contrat ID Ctr"],
                            ],
                        ],
                        [">", ["field", 62289, {"base-type": "type/Integer"}], contracts[-1]["Emplois Candidat ID"]],
                    ],
                },
            )
            contracts = client.fetch_dataset_results(client.build_dataset_query(database=2, query=query))

    @transaction.atomic()
    def _write_contract(self, contracts):
        Contract.objects.filter(pk__in=contracts).delete()
        return len(Contract.objects.bulk_create(contracts.values()))

    def fetch_riae_contracts(self):
        run_time = timezone.now()
        BATCH_SIZE = 1_000
        job_seekers_ids = list(User.objects.filter(kind=UserKind.JOB_SEEKER).values_list("pk", flat=True))
        contracts = {}
        count = 0
        synced = 0
        for contract_data in self._get_riae_contracts_data():
            count += 1
            try:
                contract_id = contract_data["Contrat Parent ID"]
                start_date = contract_data["Contrat Date Embauche"]
                if contract_end := contract_data["Contrat Date Fin Contrat"]:
                    end_date = contract_end
                    has_ended = False
                elif contract_end := contract_data["Contrat Date Sortie Definitive"]:
                    end_date = contract_end
                    has_ended = True
                else:
                    # When does it happen ?
                    end_date = None
                    has_ended = False

                if contract := contracts.get(contract_id):
                    contract.start_date = min(start_date, contract.start_date)
                    contract.has_ended = contract.has_ended or has_ended
                    if end_date and contract.end_date:
                        contract.end_date = max(contract.end_date, end_date)
                    else:
                        contract.end_date = contract.end_date or end_date
                    contract.details.append(contract_data)
                else:
                    # New contract
                    if len(contracts) >= BATCH_SIZE:
                        synced += self._write_contract(contracts)
                        print(count, synced)
                        contracts = {}

                    contracts[contract_id] = Contract(
                        pk=contract_id,
                        job_seeker_id=contract_data["Emplois Candidat ID"]
                        if contract_data["Emplois Candidat ID"] in job_seekers_ids
                        else None,
                        company=None,  # FIXME
                        start_date=start_date,
                        end_date=end_date,
                        has_ended=has_ended,
                        details=[contract_data],
                    )
            except Exception as e:
                print(e)
                print(contract_data)
                return

        synced += self._write_contract(contracts)

        # Remove old contracts not updated : they don't exist in metabase anymore
        Contract.objects.filter(updated_at__lte=run_time).delete()
        print(f"Synced {synced} Contracts")

    @dry_runnable
    def handle(self, *, data, **options):
        match data:
            case "kpi":
                action_function = {
                    "fetch": self.fetch_kpi,
                    "show": self.show_kpi,
                }[options["action"]]
                action_function()
            case "stalled-job-seekers":
                self.fetch_stalled_job_seekers()
            case "riae-contracts":
                self.fetch_riae_contracts()
