import logging
from itertools import batched

from itou.companies.enums import COMPANY_KIND_RESERVED
from itou.companies.models import Company, CompanyMembership
from itou.nexus import utils as nexus_utils
from itou.nexus.enums import Service
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

SOURCE = "emplois-de-linclusion"  # Change in each product
USER_TABLE = "users"
MEMBERSHIPS_TABLE = "memberships"
STRUCTURES_TABLE = "structures"


def log_retry_attempt(retry_state):
    logger.info("Attempt failed with outcome=%s", retry_state.outcome)


class Command(BaseCommand):
    help = "Populate nexus metabase database."
    CHUNK_SIZE = 10_000

    def batched(self, queryset):
        # NB : the iterator allows to fetch data in smaller batches.
        # With it or without, we still get all the objects that were present
        # when evaluating the queryset (in itertools.batched).
        # Any change occuring after that (new, updated or deleted line)
        # won't affect the batches.
        return batched(queryset.iterator(chunk_size=self.CHUNK_SIZE), self.CHUNK_SIZE)

    def sync_users(self):
        queryset = User.objects.filter(
            is_active=True, kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER], email__isnull=False
        )

        for users in self.batched(queryset):
            nexus_utils.sync_emplois_users(users, check_unsynchronized=self.check_unsynchronized)

    def sync_memberships(self):
        employers_qs = (
            CompanyMembership.objects.active().select_related("company").only("company__uid", "user_id", "is_admin")
        )
        for memberships in self.batched(employers_qs):
            nexus_utils.sync_emplois_memberships(memberships, check_unsynchronized=self.check_unsynchronized)

        prescribers_qs = (
            PrescriberMembership.objects.active()
            .select_related("organization")
            .only("organization__uid", "user_id", "is_admin")
        )
        for memberships in self.batched(prescribers_qs):
            nexus_utils.sync_emplois_memberships(memberships, check_unsynchronized=self.check_unsynchronized)

    def sync_structures(self):
        prescribers_qs = PrescriberOrganization.objects.select_related("insee_city")
        company_qs = Company.objects.active().exclude(kind=COMPANY_KIND_RESERVED).select_related("insee_city")

        for companies in self.batched(company_qs):
            nexus_utils.sync_emplois_structures(companies, check_unsynchronized=self.check_unsynchronized)

        for organizations in self.batched(prescribers_qs):
            nexus_utils.sync_emplois_structures(organizations, check_unsynchronized=self.check_unsynchronized)

    def add_arguments(self, parser):
        parser.add_argument("--no-checks", action="store_true", help="Don't check unsynchronized data")

    def handle(self, *args, no_checks=False, **kwargs):
        self.check_unsynchronized = not no_checks
        start_at_vals = [nexus_utils.init_full_sync(service) for service in Service.local()]
        self.sync_users()
        self.sync_structures()
        self.sync_memberships()
        for service, start_at in zip(Service.local(), start_at_vals):
            nexus_utils.complete_full_sync(service, start_at)
