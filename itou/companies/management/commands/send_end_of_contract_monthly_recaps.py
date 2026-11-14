from collections import defaultdict

from django.db.models import Exists, OuterRef
from itoutils.django.commands import dry_runnable

from itou.companies.models import Company, Contract
from itou.companies.notifications import EndOfContractMonthlyRecapForEmployerNotification
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        contracts = list(
            Contract.objects.in_monthly_recap()
            .with_has_covering_pro_support_report()
            .filter(
                # Members of a company neither active nor in grace period can no longer log into it.
                Exists(Company.objects.active_or_in_grace_period().filter(pk=OuterRef("company_id"))),
                has_covering_pro_support_report=False,
            )
            .select_related("company", "job_seeker")
            .order_by("end_date", "pk")
        )
        # Computed on the same contracts: a contract imported meanwhile would have no contacts.
        contacts = Contract.objects.filter(pk__in=[contract.pk for contract in contracts]).get_company_contacts()

        recaps = defaultdict(list)
        contracts_without_contact = 0
        for contract in contracts:
            if not contacts[contract.pk]:
                contracts_without_contact += 1
            for contact in contacts[contract.pk]:
                recaps[contract.company, contact].append(contract)

        self.logger.info("Contracts without anyone to write to: %s", contracts_without_contact)
        self.logger.info("Sending %s end of contract monthly recaps", len(recaps))
        for (company, contact), recap_contracts in recaps.items():
            EndOfContractMonthlyRecapForEmployerNotification(contact, company, contracts=recap_contracts).send()
