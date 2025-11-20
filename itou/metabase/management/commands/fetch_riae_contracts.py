from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from itou.asp.models import SiaeMeasure
from itou.companies.models import Company, Contract, SiaeConvention
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.apis.metabase import Client
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def _get_riae_contracts_data(self):
        client = Client(settings.METABASE_SITE_URL)
        QUERY_LIMIT = 100_000  # Limit to <100MB data in ram (estimated with pympler.asizeof.asizeof)

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
        return len(
            Contract.objects.bulk_create(
                contracts.values(),
                update_conflicts=True,
                unique_fields=["id"],
                update_fields=[
                    "job_seeker",
                    "company",
                    "start_date",
                    "end_date",
                    "details",
                    "updated_at",
                ],
            )
        )

    def handle(self, *args, **kwargs):
        job_seekers_ids = set(User.objects.filter(kind=UserKind.JOB_SEEKER).values_list("pk", flat=True))
        siae_mapping = {}
        conventions = SiaeConvention.objects.prefetch_related(
            Prefetch(
                "siaes",
                queryset=(Company.objects.filter(source=Company.SOURCE_ASP)[:1]),
                to_attr="siae",
            )
        )
        for convention in conventions:
            siae_mapping[(convention.asp_id, convention.kind)] = convention.siae[0] if convention.siae else None

        run_time = timezone.now()
        BATCH_SIZE = 10_000

        contracts = {}
        synced = 0
        for contract_data in self._get_riae_contracts_data():
            try:
                contract_id = contract_data["Contrat Parent ID"]
                start_date = contract_data["Contrat Date Embauche"]
                if contract_end := contract_data["Contrat Date Sortie Definitive"]:
                    # this date is the actual end of the contract, prefer it when available
                    end_date = contract_end
                elif contract_end := contract_data["Contrat Date Fin Contrat"]:
                    # this date is theoretical
                    end_date = contract_end
                else:
                    end_date = None

                if contract_data["Contrat Mesure Disp Code"] not in SiaeMeasure:
                    # We don't need these contracts since we don't have the corresponding company
                    continue

                if end_date and start_date > end_date:
                    # There are a few contrats that end before they start: drop them
                    continue

                if contract := contracts.get(contract_id):
                    contract.start_date = min(start_date, contract.start_date)
                    if end_date and contract.end_date:
                        contract.end_date = max(contract.end_date, end_date)
                    else:
                        contract.end_date = contract.end_date or end_date
                    contract.details.append(contract_data)
                else:
                    # New contract
                    if len(contracts) >= BATCH_SIZE:
                        synced += self._write_contract(contracts)
                        contracts = {}

                    contracts[contract_id] = Contract(
                        pk=contract_id,
                        job_seeker_id=(
                            contract_data["Emplois Candidat ID"]
                            if contract_data["Emplois Candidat ID"] in job_seekers_ids
                            else None
                        ),
                        company=siae_mapping.get(
                            (
                                contract_data["Contrat ID Structure"],
                                SiaeMeasure(contract_data["Contrat Mesure Disp Code"]).name,
                            ),
                            None,
                        ),
                        start_date=start_date,
                        end_date=end_date,
                        details=[contract_data],
                    )
            except Exception:
                self.logger.exception("Failed to upsert Contract")

        synced += self._write_contract(contracts)

        # Remove old contracts not updated : they don't exist in metabase anymore
        Contract.objects.filter(updated_at__lte=run_time).delete()
        self.logger.info(f"Synced {synced} Contracts")
