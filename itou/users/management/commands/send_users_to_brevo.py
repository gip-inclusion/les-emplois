import datetime
import logging
from itertools import batched

import httpx
from allauth.account.models import EmailAddress
from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.companies.enums import CompanyKind
from itou.companies.models import CompanyMembership
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

# https://app.brevo.com/contact/list-listing
BREVO_LES_EMPLOIS_LIST_ID = 31
BREVO_CANDIDATS_LIST_ID = 82
BREVO_CANDIDATS_AUTONOMES_BLOQUES_LIST_ID = 83
BREVO_API_URL = "https://api.brevo.com/v3"


def professional_serializer(user, brevo_type):
    return {
        "email": user.email,
        "attributes": {
            "prenom": user.first_name.title(),
            "nom": user.last_name.upper(),
            "date_inscription": timezone.localdate(user.date_joined).isoformat(),
            "type": brevo_type,
        },
    }


def employer_serializer(user):
    return professional_serializer(user, "employeur")


def authorized_prescriber_serializer(user):
    return professional_serializer(user, "prescripteur habilité")


def prescriber_serializer(user):
    return professional_serializer(user, "orienteur")


def job_seeker_serializer(user):
    return {
        "email": user.email,
        "attributes": {
            "id": user.pk,
            "prenom": user.first_name.title(),
            "nom": user.last_name.upper(),
            "departement": user.job_seeker_department,
            "date_inscription": timezone.localdate(user.date_joined).isoformat(),
        },
    }


class BrevoClient:
    IMPORT_BATCH_SIZE = 1000

    def __init__(self):
        self.client = httpx.Client(
            headers={
                "accept": "application/json",
                "api-key": settings.BREVO_API_KEY,
            }
        )

    def _import_contacts(self, users, list_id, serializer):
        response = self.client.post(
            f"{BREVO_API_URL}/contacts/import",
            headers={"Content-Type": "application/json"},
            json={
                "listIds": [list_id],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,  # Don't update because we don't want to update emailBlacklist
                "emptyContactsAttributes": False,
                "jsonBody": [serializer(user) for user in users],
            },
        )
        if response.status_code != 202:
            logger.error(
                "Brevo API: Some emails were not imported, status_code=%d, content=%s",
                response.status_code,
                response.text,
            )

    def import_users(self, users, list_id, serializer):
        for batch in batched(users, self.IMPORT_BATCH_SIZE):
            if batch:
                self._import_contacts(batch, list_id, serializer)


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
        self.import_professionals(client, wet_run=wet_run)
        self.import_job_seekers(client, wet_run=wet_run)

    def import_professionals(self, client, *, wet_run):
        professional_qs = (
            User.objects.filter(kind__in=[UserKind.PRESCRIBER, UserKind.EMPLOYER])
            .filter(
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
        self.import_employers(client, professional_qs, wet_run=wet_run)
        self.import_prescribers(client, professional_qs, wet_run=wet_run)

    def import_employers(self, client, professional_qs, *, wet_run):
        employers = list(
            professional_qs.filter(kind=UserKind.EMPLOYER).filter(
                Exists(
                    CompanyMembership.objects.filter(
                        user_id=OuterRef("pk"),
                        is_active=True,
                        company__kind__in=CompanyKind.siae_kinds(),
                    )
                )
            )
        )
        logger.info("SIAE users count: %d", len(employers))
        if wet_run:
            client.import_users(employers, BREVO_LES_EMPLOIS_LIST_ID, employer_serializer)

    def import_prescribers(self, client, professional_qs, *, wet_run):
        all_prescribers = professional_qs.filter(kind=UserKind.PRESCRIBER)
        authorized_prescriber_memberships = PrescriberMembership.objects.filter(
            user_id=OuterRef("pk"),
            is_active=True,
            organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED,
        )
        prescribers = list(all_prescribers.filter(Exists(authorized_prescriber_memberships)))
        logger.info("Prescribers count: %d", len(prescribers))
        if wet_run:
            client.import_users(prescribers, BREVO_LES_EMPLOIS_LIST_ID, authorized_prescriber_serializer)

        orienteurs = list(all_prescribers.exclude(Exists(authorized_prescriber_memberships)))
        logger.info("Orienteurs count: %d", len(orienteurs))
        if wet_run:
            client.import_users(orienteurs, BREVO_LES_EMPLOIS_LIST_ID, prescriber_serializer)

    def import_job_seekers(self, client, *, wet_run):
        job_seekers = User.objects.filter(
            Q(
                Exists(
                    EmailAddress.objects.filter(
                        user_id=OuterRef("pk"),
                        email=OuterRef("email"),
                        primary=True,
                        verified=True,
                    )
                )
            )
            | Q(
                identity_provider__in=[
                    IdentityProvider.FRANCE_CONNECT,
                    IdentityProvider.PE_CONNECT,
                ]
            ),
            kind=UserKind.JOB_SEEKER,
            is_active=True,
        ).order_by("pk")

        midnight_today = datetime.datetime.combine(
            timezone.localdate(),
            datetime.time.min,
            tzinfo=timezone.get_current_timezone(),
        )
        a_month_ago = midnight_today - datetime.timedelta(days=30)
        recently_joined = job_seekers.filter(date_joined__gte=a_month_ago)
        logger.info("Job seekers count: %d", len(recently_joined))
        if wet_run:
            client.import_users(recently_joined, BREVO_CANDIDATS_LIST_ID, job_seeker_serializer)

        stalled_autonomous_job_seekers = job_seekers.filter(jobseeker_profile__is_stalled=True)
        logger.info("Stalled autonomous job seekers count: %d", len(stalled_autonomous_job_seekers))
        if wet_run:
            client.import_users(
                stalled_autonomous_job_seekers,
                BREVO_CANDIDATS_AUTONOMES_BLOQUES_LIST_ID,
                job_seeker_serializer,
            )
