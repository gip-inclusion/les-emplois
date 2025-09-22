from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.archive.tasks import async_delete_contact
from itou.users.models import User
from itou.utils.brevo import BrevoClient
from itou.utils.command import BaseCommand, dry_runnable


def modified_before(contact, cutoff_date):
    date_str = contact.get("modifiedAt") or contact.get("createdAt")
    if not date_str:
        return False

    try:
        return datetime.fromisoformat(date_str) < cutoff_date
    except (TypeError, ValueError):
        return False


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Delete obsolete emails from Brevo",
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
    def handle(self, *args, verbosity, wet_run, offset=0, **options):
        limit = 1000
        emails_to_delete_count = 0
        two_years_ago = timezone.now() - relativedelta(years=2)

        with BrevoClient() as brevo_client:
            while True:
                try:
                    contacts = brevo_client.list_contacts(limit=limit, offset=offset)
                except Exception as e:
                    self.logger.error("Error fetching contacts at offset %s: %s", offset, str(e))
                    break

                if not contacts:
                    self.logger.info("No more contact to process at offset %d", offset)
                    break

                # Case 1 : email is used by active user in DB: we do not remove from Brevo
                # Case 2 : email is not used by active user and has been modified in Brevo
                #          less than 2 years ago: we do not remove from Brevo
                # Case 3 : email is not used by active user and has not been modified in Brevo
                #          less than 2 years ago: we delete it

                # Collect emails from Brevo
                emails_modified_long_time_ago_said_brevo = {
                    contact.get("email", "").lower() for contact in contacts if modified_before(contact, two_years_ago)
                }
                self.logger.info(
                    "Found %d emails unmodified since %s at offset %d",
                    len(emails_modified_long_time_ago_said_brevo),
                    two_years_ago,
                    offset,
                )

                # Collect emails from DB
                known_emails = set(
                    User.objects.filter(
                        email__in=emails_modified_long_time_ago_said_brevo, is_active=True
                    ).values_list("email", flat=True)
                )

                # Get emails to delete, excluding the ones known in DB
                emails_to_delete = emails_modified_long_time_ago_said_brevo - known_emails
                self.logger.info("Found %d emails to delete at offset %d", len(emails_to_delete), offset)
                emails_to_delete_count += len(emails_to_delete)

                for email in emails_to_delete:
                    if wet_run:
                        if verbosity > 1:
                            self.logger.info("Deleting contact: %s", email)
                        async_delete_contact(email)
                    else:
                        self.logger.info("[DRY RUN] Would delete contact: %s", email)

                self.logger.info("Found %d emails to delete at offset %d", len(emails_to_delete), offset)

                offset += limit

        self.logger.info("Found %d emails to delete", emails_to_delete_count)
