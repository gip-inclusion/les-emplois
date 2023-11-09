import datetime
import logging
import time

import httpx
from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.management import BaseCommand
from django.db.models import Exists, OuterRef
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.companies.models import CompanyMembership
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.iterators import chunks


logger = logging.getLogger(__name__)

MAILJET_API_URL = "https://api.mailjet.com/v3/"
# https://app.mailjet.com/contacts/lists/show/aG3w
NEW_SIAE_LISTID = 2544946
# https://app.mailjet.com/contacts/lists/show/aG3x
NEW_PE_LISTID = 2544947
# https://app.mailjet.com/contacts/lists/show/aG3z
NEW_PRESCRIBERS_LISTID = 2544949
# https://app.mailjet.com/contacts/lists/show/aG3y
NEW_ORIENTEURS_LISTID = 2544948


class Command(BaseCommand):
    BATCH_SIZE = 1_000

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Enroll new users to a mailing list in MailJet",
        )

    @staticmethod
    def campaign_start():
        # Users who joined before this date are not part of the mailing campaign.
        return max(
            timezone.make_aware(datetime.datetime(2023, 4, 23)),
            timezone.now() - datetime.timedelta(days=365),
        )

    @staticmethod
    def manage_url(list_id):
        # https://dev.mailjet.com/email/guides/contact-management/#manage-multiple-contacts-in-a-list
        # https://dev.mailjet.com/email/reference/contacts/bulk-contact-management/#v3_post_contactslist_list_ID_managemanycontacts
        return f"{MAILJET_API_URL}REST/contactslist/{list_id}/managemanycontacts"

    @staticmethod
    def monitor_url(list_id, job_id):
        # https://dev.mailjet.com/email/reference/contacts/bulk-contact-management/#v3_get_contactslist_list_ID_managemanycontacts_job_ID
        return f"{MAILJET_API_URL}REST/contactslist/{list_id}/managemanycontacts/{job_id}"

    def send_to_mailjet(self, client, list_id, users):
        response = client.post(
            self.manage_url(list_id),
            json={
                "Action": "addnoforce",
                "Contacts": [
                    {
                        "Email": user.email,
                        "Name": user.get_full_name(),
                    }
                    for user in users
                ],
            },
        )
        response.raise_for_status()
        response = response.json()
        [data] = response["Data"]
        return data["JobID"]

    def poll_completion(self, client, list_id, job_id):
        end = timezone.now() + datetime.timedelta(minutes=5)
        while timezone.now() < end:
            response = client.get(self.monitor_url(list_id, job_id))
            response.raise_for_status()
            response = response.json()
            [data] = response["Data"]
            if data["Status"] in ["Completed", "Error"]:
                if error := data["Error"]:
                    logger.error("MailJet errors for list ID %s: %s", list_id, error)
                if errorfile := data["ErrorFile"]:
                    logger.error("MailJet errors file for list ID %s: %s", list_id, errorfile)
                job_end = datetime.datetime.fromisoformat(data["JobEnd"])
                job_start = datetime.datetime.fromisoformat(data["JobStart"])
                duration = (job_end - job_start).total_seconds()
                logger.info("MailJet processed batch for list ID %s in %d seconds.", list_id, duration)
                return
            else:
                time.sleep(2)

    @monitor(monitor_slug="new-users-to-mailjet")
    def handle(self, *args, wet_run, **options):
        users = (
            User.objects.exclude(kind=UserKind.JOB_SEEKER)
            .filter(
                Exists(
                    EmailAddress.objects.filter(
                        user_id=OuterRef("pk"),
                        email=OuterRef("email"),
                        primary=True,
                        verified=True,
                    )
                ),
                date_joined__gte=self.campaign_start(),
                is_active=True,
            )
            .order_by("email")
        )
        employers = users.filter(kind=UserKind.EMPLOYER).filter(
            Exists(
                CompanyMembership.objects.filter(
                    user_id=OuterRef("pk"),
                    is_active=True,
                    company__kind__in=SIAE_WITH_CONVENTION_KINDS,
                )
            )
        )
        all_prescribers = users.filter(kind=UserKind.PRESCRIBER)
        prescriber_membership_qs = PrescriberMembership.objects.filter(user_id=OuterRef("pk"), is_active=True)
        pe_prescribers = users.filter(
            Exists(prescriber_membership_qs.filter(organization__kind=PrescriberOrganizationKind.PE))
        )
        prescribers = all_prescribers.filter(Exists(prescriber_membership_qs.filter(organization__is_authorized=True)))
        orienteurs = all_prescribers.exclude(
            pk__in=PrescriberMembership.objects.filter(is_active=True, organization__is_authorized=True).values_list(
                "user_id", flat=True
            )
        )

        logger.info("SIAE users count: %d", len(employers))
        logger.info("PE prescribers count: %d", len(pe_prescribers))
        logger.info("Prescribers count: %d", len(prescribers))
        logger.info("Orienteurs count: %d", len(orienteurs))

        if wet_run:
            with httpx.Client(
                auth=(settings.MAILJET_API_KEY_PRINCIPAL, settings.MAILJET_SECRET_KEY_PRINCIPAL),
                headers={"Content-Type": "application/json"},
            ) as client:
                for list_id, users in [
                    (NEW_SIAE_LISTID, employers),
                    (NEW_PE_LISTID, pe_prescribers),
                    (NEW_PRESCRIBERS_LISTID, prescribers),
                    (NEW_ORIENTEURS_LISTID, orienteurs),
                ]:
                    for chunk in chunks(users, self.BATCH_SIZE):
                        if chunk:
                            job_id = self.send_to_mailjet(client, list_id, chunk)
                            self.poll_completion(client, list_id, job_id)
