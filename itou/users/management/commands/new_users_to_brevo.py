import enum
import logging
from itertools import batched

import httpx
from allauth.account.models import EmailAddress
from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from sentry_sdk.crons import monitor

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.companies.models import CompanyMembership
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

# https://app.brevo.com/contact/list-listing
BREVO_LIST_ID = 31
BREVO_API_URL = "https://api.brevo.com/v3"


class UserCategory(enum.Enum):
    PRESCRIBER = "prescripteur habilité"
    ORIENTEUR = "orienteur"
    EMPLOYEUR = "employeur"


class BrevoClient:
    IMPORT_BATCH_SIZE = 1000

    def __init__(self):
        self.client = httpx.Client(
            headers={
                "accept": "application/json",
                "api-key": settings.BREVO_API_KEY,
            }
        )

    def _import_contacts(self, users_data, category):
        data = [
            {
                "email": user["email"],
                "attributes": {
                    "prenom": user["first_name"].title(),
                    "nom": user["last_name"].upper(),
                    "date_inscription": user["date_joined"].strftime("%Y-%m-%d"),
                    "type": category.value,
                },
            }
            for user in users_data
        ]

        response = self.client.post(
            f"{BREVO_API_URL}/contacts/import",
            headers={"Content-Type": "application/json"},
            json={
                "listIds": [BREVO_LIST_ID],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,  # Don't update because we don't want to update emailBlacklist
                "emptyContactsAttributes": False,
                "jsonBody": data,
            },
        )
        if response.status_code != 202:
            logger.error(
                "Brevo API: Some emails were not imported, status_code=%d, content=%s",
                response.status_code,
                response.content.decode(),
            )

    def import_users(self, users, category):
        for batch in batched(users, self.IMPORT_BATCH_SIZE):
            if batch:
                self._import_contacts(batch, category)


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Enroll new users to a mailing list in Brevo",
        )

    @monitor(
        monitor_slug="new-users-to-brevo",
        monitor_config={
            "schedule": {"type": "crontab", "value": "30 1 * * *"},
            "checkin_margin": 30,
            "max_runtime": 30,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *args, wet_run, **options):
        client = BrevoClient()

        users = (
            User.objects.filter(kind__in=[UserKind.PRESCRIBER, UserKind.EMPLOYER])
            .filter(
                # Someday only filter on identity_provider ?
                Exists(
                    EmailAddress.objects.filter(
                        user_id=OuterRef("pk"),
                        email=OuterRef("email"),
                        primary=True,
                        verified=True,
                    )
                )
                | Q(
                    identity_provider__in=[IdentityProvider.INCLUSION_CONNECT, IdentityProvider.PRO_CONNECT]
                ),  # the SSO verifies emails on its own
                is_active=True,
            )
            .order_by("email")
        )
        employers = list(
            users.filter(kind=UserKind.EMPLOYER)
            .filter(
                Exists(
                    CompanyMembership.objects.filter(
                        user_id=OuterRef("pk"),
                        is_active=True,
                        company__kind__in=SIAE_WITH_CONVENTION_KINDS,
                    )
                )
            )
            .values("email", "first_name", "last_name", "date_joined")
        )

        all_prescribers = users.filter(kind=UserKind.PRESCRIBER)
        prescriber_membership_qs = PrescriberMembership.objects.filter(user_id=OuterRef("pk"), is_active=True)
        prescribers = list(
            all_prescribers.filter(Exists(prescriber_membership_qs.filter(organization__is_authorized=True))).values(
                "email", "first_name", "last_name", "date_joined"
            )
        )
        orienteurs = list(
            all_prescribers.exclude(Exists(prescriber_membership_qs.filter(organization__is_authorized=True))).values(
                "email", "first_name", "last_name", "date_joined"
            )
        )

        logger.info("SIAE users count: %d", len(employers))
        logger.info("Prescribers count: %d", len(prescribers))
        logger.info("Orienteurs count: %d", len(orienteurs))

        if wet_run:
            for category, users in [
                (UserCategory.EMPLOYEUR, employers),
                (UserCategory.PRESCRIBER, prescribers),
                (UserCategory.ORIENTEUR, orienteurs),
            ]:
                client.import_users(users, category)
