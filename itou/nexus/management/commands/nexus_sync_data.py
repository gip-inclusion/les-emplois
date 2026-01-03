"""
Full sync of emplois data
"""

import logging
from itertools import batched

import tenacity

from itou.companies.models import Company, CompanyMembership
from itou.nexus import utils as nexus_utils
from itou.nexus.enums import Service
from itou.nexus.models import NexusUser
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

    def sync_users(self):
        queryset = User.objects.filter(
            is_active=True, kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER], email__isnull=False
        )

        for users in batched(queryset, 10_000):
            nexus_utils.sync_users(
                [nexus_utils.build_user(nexus_utils.serialize_user(user), Service.EMPLOIS) for user in users]
            )

        for service in [Service.PILOTAGE, Service.MON_RECAP]:
            queryset = queryset.filter(
                id__in=list(NexusUser.include_old.filter(source=service).values_list("source_id", flat=True))
            )
            for users in batched(queryset, 10_000):
                nexus_utils.sync_users(
                    [nexus_utils.build_user(nexus_utils.serialize_user(user), service) for user in users],
                    update_only=True,
                )

    def sync_memberships(self):
        employers_qs = (
            CompanyMembership.objects.active().select_related("company").only("company__uid", "user_id", "is_admin")
        )
        prescribers_qs = (
            PrescriberMembership.objects.active()
            .select_related("organization")
            .only("organization__uid", "user_id", "is_admin")
        )

        for memberships in batched(employers_qs, 10_000):
            nexus_utils.sync_memberships(
                [
                    nexus_utils.build_membership(nexus_utils.serialize_membership(membership), Service.EMPLOIS)
                    for membership in memberships
                ]
            )
        for memberships in batched(prescribers_qs, 10_000):
            nexus_utils.sync_memberships(
                [
                    nexus_utils.build_membership(nexus_utils.serialize_membership(membership), Service.EMPLOIS)
                    for membership in memberships
                ]
            )

    def sync_structures(self):
        prescribers_qs = PrescriberOrganization.objects.select_related("insee_city")
        company_qs = Company.objects.active().select_related("insee_city")

        for companies in batched(company_qs, 10_000):
            nexus_utils.sync_structures(
                [
                    nexus_utils.build_structure(nexus_utils.serialize_structure(company), Service.EMPLOIS)
                    for company in companies
                ]
            )
        for organizations in batched(prescribers_qs, 10_000):
            nexus_utils.sync_structures(
                [
                    nexus_utils.build_structure(nexus_utils.serialize_structure(organization), Service.EMPLOIS)
                    for organization in organizations
                ]
            )

    def add_arguments(self, parser):
        parser.add_argument("--reset-tables", action="store_true", help="Reset the table schema")

    @tenacity.retry(
        retry=tenacity.retry_if_not_exception_type(RuntimeError),
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_fixed(5),
        after=log_retry_attempt,
    )
    def handle(self, *args, **kwargs):
        services = [Service.EMPLOIS, Service.PILOTAGE, Service.MON_RECAP]
        start_at = [nexus_utils.init_full_sync(service) for service in services]
        self.sync_users()
        self.sync_structures()
        self.sync_memberships()
        for service, start_at in zip(services, start_at):
            nexus_utils.complete_full_sync(service, start_at)
