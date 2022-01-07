from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.approvals.models import Approval


class Command(BaseCommand):
    """
    Notify

    To run:
        django-admin pe_backport_all_approvals --dry-run
    """

    help = "Notifies Pole Emploi of all the approvals that start on a given date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print the valid approvals that start today"
        )

    def backport_approvals_to_pole_emploi(self, dry_run: bool):
        """
        Pole emploi wants to be notified everyday of the valid approvals that start on this day
        that they did not already receive
        """
        # We want to send to pole emploi the valid approvals that have already been created
        today = timezone.now()
        approvals = Approval.objects.filter(start_at__lt=today).valid()
        if dry_run:
            self.stdout.write("DRY-RUN. NO NOTIFICATION WILL BE PERFORMED")
            self.stdout.write(f"{approvals.count()} valid approvals")
        else:
            start_date_fr = timezone.now()
            self.stdout.write(f"Notifying Pole Emploi for {approvals.count()} valid approvals for day {start_date_fr}")
            print(approvals.count())
            # for approval in approvals:
            #     print(approval.id)

    def handle(self, dry_run=False, **options):
        self.backport_approvals_to_pole_emploi(dry_run)
