from django.db import transaction

from itou.communications.models import NotificationRecord, NotificationSettings
from itou.companies.models import Company, CompanyMembership
from itou.users.models import User
from itou.utils.command import BaseCommand


def notification_record(name):
    try:
        return NotificationRecord.objects.actives().filter(can_be_disabled=True).get(notification_class=name)
    except NotificationRecord.DoesNotExist:
        raise ValueError()


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user", type=int, help="PK of the user to add to companies")
        parser.add_argument(
            "--siren",
            dest="sirens",
            required=True,
            nargs="+",
            type=int,
            help="Sirens of the companies to add the user to",
        )
        parser.add_argument(
            "--disable-notification",
            nargs="*",
            default=[],
            type=notification_record,
            dest="disabled_notifications",
            help="Notification class to disable for that user and those companies",
        )
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @transaction.atomic
    def handle(self, user, sirens, *, disabled_notifications=None, wet_run=False, **options):
        user = User.objects.get(pk=user)
        self.stdout.write(f"Add {user=} for {sirens=} with {disabled_notifications=}")

        for siren in sirens:
            for company in Company.objects.filter(siret__startswith=siren):
                self.stdout.write(f"Processing siret={company.siret} {company=}")
                # Link user to the company
                CompanyMembership.objects.update_or_create(
                    company=company, user=user, create_defaults={"is_admin": True}, defaults={"is_admin": True}
                )
                # Disable some notifications for that user and company
                notification_settings, _ = NotificationSettings.get_or_create(user, company)
                for notification in disabled_notifications:
                    notification_settings.disabled_notifications.add(notification)

        if not wet_run:
            raise Exception("DRY RUN")
