from django.core.management.base import BaseCommand

from itou.approvals import enums as approvals_enums
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow


# The support team sometimes fixes issues by generating a PASS, filling out the necessary information,
# setting a Job Application as accepted, etc... all in the admin.
#
# One of the common "mistakes" made during this process is to forget to fill the "eligibility diagnosis"
# cell of the job application. We can't blame them, it's a kind of loose denormalization anyway.
#
# But it can be many, many other very specific cases. This command is there to help printing a summary
# of the problematic cases from time to time.


class Command(BaseCommand):
    help = "Prints the accepted job applications that do not have eligibility diagnoses for no obvious reason"

    def handle(self, **options):
        queryset = (
            JobApplication.objects.filter(
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                eligibility_diagnosis=None,
                to_siae__kind__in=SIAE_WITH_CONVENTION_KINDS,
                approval__isnull=False,
            )
            .exclude(origin=job_applications_enums.Origin.AI_STOCK)
            .exclude(approval__origin__in=[approvals_enums.Origin.AI_STOCK, approvals_enums.Origin.PE_APPROVAL])
            .order_by("approval__created_at")
        )
        if queryset.count() == 0:
            return

        self.stdout.write("number,created_at,started_at,end_at,created_by,job_seeker\n")
        for ja in queryset:
            self.stdout.write(
                ",".join(
                    [
                        ja.approval.number,
                        ja.approval.created_at.isoformat(),
                        ja.approval.start_at.isoformat(),
                        ja.approval.end_at.isoformat(),
                        str(ja.approval.created_by),
                        str(ja.approval.user),
                    ]
                )
                + "\n"
            )
