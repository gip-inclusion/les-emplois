import logging

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
        django-admin send_all_approvals_to_pe --dry-run --verbosity=2
        django-admin send_all_approvals_to_pe
    """

    help = "Notifies Pole Emploi of all the approvals that they did not already accept."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print the valid approvals that start today"
        )

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def batch_notify_pole_emploi(self, dry_run: bool):
        """
        Pole emploi wants to be notified of the existing approvals we own
        that they did not already receive
        """
        # We only want to send to Pole Emploi the approvals tied to an accepted job_application
        approvals = Approval.objects.filter().valid()
        job_applications = JobApplication.objects.filter(
            approval__in=approvals, state=JobApplicationWorkflow.STATE_ACCEPTED
        )
        # We need to discard the notifications we sent and that they alreay accepted
        notifs_ok = JobApplicationPoleEmploiNotificationLog.objects.filter(
            status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
        )
        job_applications = job_applications.exclude(pk__in=Subquery(notifs_ok.values("job_application_id")))

        if dry_run:
            self.logger.debug("DRY-RUN. NO NOTIFICATION WILL BE PERFORMED")
            self.logger.debug(f"{approvals.count()} valid approvals would be sent")
        else:
            self.logger.debug(f"Notifying Pole Emploi for {approvals.count()} valid approvals")
            # Job application are added to the queue and will be dealt with later on
            for job_application in job_applications:
                self.logger.debug(
                    "{},{},{}".format(
                        job_application.id, job_application.hiring_start_at, job_application.hiring_end_at
                    )
                )
                job_application.notify_pole_emploi_accepted()

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.batch_notify_pole_emploi(dry_run)
