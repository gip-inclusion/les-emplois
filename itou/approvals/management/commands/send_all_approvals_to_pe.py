import datetime

from django.core.management.base import BaseCommand
from django.db.models import CharField, Q, Subquery
from django.db.models.functions import Length

from itou.approvals.models import Approval
from itou.job_applications.models import (
    JobApplication,
    JobApplicationPoleEmploiNotificationLog,
    JobApplicationWorkflow,
)
from itou.job_applications.tasks import notify_pole_emploi_pass


# on this day we started notifying Pole Emploi with each new PASS IAE that would be created.
PE_API_START_DATE = datetime.date(2021, 12, 16)


class Command(BaseCommand):

    help = "Notifies Pole Emploi of all the approvals that they did not already accept."

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, wet_run=False, **options):
        # only send Pole Emploi the approvals tied to an accepted job_application
        approvals = Approval.objects.filter(start_at__lt=PE_API_START_DATE)
        job_applications = JobApplication.objects.filter(
            approval__pk__in=Subquery(approvals.values("pk")), state=JobApplicationWorkflow.STATE_ACCEPTED
        )
        self.stdout.write(f"approvals          count={approvals.count()}")
        self.stdout.write(f"job_applications   count={job_applications.count()}")

        CharField.register_lookup(Length)
        with_valid_users = job_applications.exclude(Q(job_seeker__first_name="") | Q(job_seeker__last_name="")).filter(
            job_seeker__isnull=False,
            job_seeker__nir__length__gte=13,
            job_seeker__birthdate__isnull=False,
        )
        self.stdout.write(f"> with valid users count={with_valid_users.count()}")

        not_already_sent = with_valid_users.exclude(
            jobapplicationpoleemploinotificationlog__status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
        )
        self.stdout.write(f"> not already sent count={not_already_sent.count()}")
        for job_application in not_already_sent:
            self.stdout.write(
                "> processing job_application id={} hiring_start_at={} hiring_end_at={}".format(
                    job_application.id, job_application.hiring_start_at, job_application.hiring_end_at
                )
            )
            if wet_run:
                notify_pole_emploi_pass(job_application, job_application.job_seeker)
