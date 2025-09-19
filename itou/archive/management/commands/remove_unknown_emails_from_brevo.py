from datetime import datetime, timedelta

from django.db.models.functions import Lower
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.archive.tasks import async_delete_contact
from itou.users.models import User
from itou.utils.brevo import BrevoClient, BrevoListID
from itou.utils.command import BaseCommand, dry_runnable


def modified_before(contact, cutoff):
    try:
        return datetime.fromisoformat(contact["modifiedAt"]) < cutoff
    except (KeyError, TypeError, ValueError):
        return False


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the anonymization of cancelled approvals",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Restart a failing run at the specified offset",
        )

    @monitor(
        monitor_slug="remove_unknown_emails_from_brevo",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 22 1 * *"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    @dry_runnable
    def handle(self, *args, wet_run, offset=0, **options):
        self.wet_run = wet_run
        limit = 1000
        emails_to_delete_count = 0
        two_years_ago = timezone.now() - timedelta(days=2 * 365)

        while True:
            with BrevoClient() as brevo_client:
                try:
                    content = brevo_client.list_contacts(limit=limit, offset=offset)
                except Exception as e:
                    self.logger.error("Error fetching contacts at offset %s: %s", offset, str(e))
                    break

            contacts = content.get("contacts", [])
            if not contacts:
                self.logger.info("No more contacts to process.")
                break

            offset += limit

            # Collect & lowerize emails from Brevo
            # Case 1 : email in BrevoListID.LES_EMPLOIS, including other lists or not
            # Delete if not found in DB
            emails = {
                contact.get("email", "").lower()
                for contact in contacts
                if "email" in contact and contact["listIds"] == [BrevoListID.LES_EMPLOIS]
            }
            # Case 2 : email not in BrevoListID.LES_EMPLOIS
            # Delete if modifiedAt older than 2 years
            other_emails = {
                contact.get("email", "").lower()
                for contact in contacts
                if "email" in contact
                and BrevoListID.LES_EMPLOIS not in contact["listIds"]
                and modified_before(contact, two_years_ago)
            }

            # Collect emails from DB
            known_emails = set(
                User.objects.annotate(email_lower=Lower("email"))
                .filter(email_lower__in=emails)
                .values_list("email_lower", flat=True)
            )

            # Get emails to delete, excluding the ones known in DB
            emails_to_delete = (emails - known_emails) | other_emails
            emails_to_delete_count += len(emails_to_delete)

            for email in emails_to_delete:
                if wet_run:
                    self.logger.info("Deleting contact: %s", email)
                    async_delete_contact(email)
                else:
                    self.logger.info("[DRY RUN] Would delete contact: %s", email)

        self.logger.info("Total emails to delete in Brevo: %s", emails_to_delete_count)
