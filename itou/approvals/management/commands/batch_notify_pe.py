import datetime

from django.utils import timezone

from itou.approvals.models import Approval
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.management_commands import ItouBaseCommand


DATE_FORMAT = "%d/%m/%y"


class Command(ItouBaseCommand):
    """
    Notify

    To run:
        django-admin batch_notify_pe --start_date="04/01/2022" --dry-run --verbosity=2
        django-admin batch_notify_pe
    """

    help = "Notifies Pole Emploi of all the approvals that start on a given date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            dest="start_date_str",
            required=False,
            action="store",
            help=f"Start date of the approvals in the form {DATE_FORMAT.replace('%', '%%')}",
        )
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print the valid approvals that start today"
        )

    def parse_start_date_str(self, start_date_str):
        """Parses the user-provided start date.
        It can break in many ways (empty input, invalid date, invalid format…),
        so when it cannot parse the date it will return today’s date
        """
        value = str(start_date_str).strip()
        if value != "":
            try:
                return datetime.datetime.strptime(value, DATE_FORMAT).date()
            except ValueError:
                pass
        return timezone.now()

    def batch_notify_pole_emploi(self, start_date, dry_run: bool):
        """
        Pole emploi wants to be notified everyday of the valid approvals that start on this day
        that they did not already receive
        """
        today = timezone.now()
        # We only want to send to Pole Emploi the approvals that have already been created
        # but which starts today, hence the created_at filter
        approvals = Approval.objects.filter(start_at=start_date, created_at__lt=today).valid()
        job_applications = JobApplication.objects.filter(
            approval__in=approvals, state=JobApplicationWorkflow.STATE_ACCEPTED
        )
        if dry_run:
            self.logger.debug("DRY-RUN. NO NOTIFICATION WILL BE PERFORMED")
            self.logger.debug(f"{approvals.count()} valid approvals start on {start_date.strftime(DATE_FORMAT)}")
        else:
            start_date_fr = start_date.strftime(DATE_FORMAT)
            self.logger.debug(f"Notifying Pole Emploi for {approvals.count()} valid approvals for day {start_date_fr}")
            # Job application are added to the queue and will be dealt with later on
            for job_application in job_applications:
                self.logger.debug(
                    "{},{},{}".format(
                        job_application.id, job_application.hiring_start_at, job_application.hiring_end_at
                    )
                )
                job_application.notify_pole_emploi_accepted()

    def handle(self, start_date_str, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        start_date = self.parse_start_date_str(start_date_str)
        self.batch_notify_pole_emploi(start_date, dry_run)
