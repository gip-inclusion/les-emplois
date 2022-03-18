from django.core.management.base import BaseCommand
from django.db.models import Subquery

from itou.approvals.models import Approval
from itou.job_applications.models import (
    JobApplication,
    JobApplicationPoleEmploiNotificationLog,
    JobApplicationWorkflow,
)


class Command(BaseCommand):
    """
    Notify

    To run:
        # debug
        django-admin send_all_approvals_to_pe --dry-run --verbosity=2
        # prod: real notifications are sent
        django-admin send_all_approvals_to_pe --no-dry-run
    """

    help = "Notifies Pole Emploi of all the approvals that they did not already accept."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print the valid approvals that start today"
        )
        parser.add_argument(
            "--no-dry-run", dest="dry_run", action="store_false", help="Send real notifications to Pole Emploi"
        )

    def batch_notify_pole_emploi(self, dry_run: bool, verbosity: int):
        """
        Pole emploi wants to be notified of the existing approvals we own
        that they did not already receive
        """
        # We only want to send to Pole Emploi the approvals tied to an accepted job_application
        approvals = Approval.objects.filter().valid()
        job_applications = JobApplication.objects.filter(
            approval__pk__in=Subquery(approvals.values("pk")), state=JobApplicationWorkflow.STATE_ACCEPTED
        )
        # We need to discard the notifications we sent and that they alreay accepted
        notifs_ok = JobApplicationPoleEmploiNotificationLog.objects.filter(
            status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
        )
        job_applications = job_applications.exclude(pk__in=Subquery(notifs_ok.values("job_application_id")))

        if dry_run:
            self.stdout.write("DRY-RUN. NO NOTIFICATION WILL BE PERFORMED")
            self.stdout.write(f"{approvals.count()} valid approvals would be sent")
        else:
            self.stdout.debug(f"Notifying Pole Emploi for {approvals.count()} valid approvals")
            # Job application are added to the queue and will be dealt with later on
            for job_application in job_applications:
                if verbosity > 1:
                    self.stdout.write(
                        "{},{},{}".format(
                            job_application.id, job_application.hiring_start_at, job_application.hiring_end_at
                        )
                    )
                job_application.notify_pole_emploi_accepted()

    def handle(self, dry_run=False, **options):
        self.batch_notify_pole_emploi(dry_run, options.get("verbosity"))
