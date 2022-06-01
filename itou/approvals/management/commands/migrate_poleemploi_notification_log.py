import re

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

from itou.approvals import enums as approvals_enums
from itou.job_applications.models import JobApplication, JobApplicationPoleEmploiNotificationLog


def exit_code_from_details(log_details):
    """A custom function to try and extract a "real" code from the hot mess that
    is the "details" field.
    Anything that is not an error code from the PE API is considered a retryable failure.

    This code is ugly but that the best I could do with the data currently at hand.
    """
    if "codeSortie" in log_details:
        return re.search('.*codeSortie":"(.*?)"', log_details).group(1)
    elif "codeError" in log_details:
        return re.search('.*codeError":"(.*?)"', log_details).group(1)
    elif "400 R021" in log_details:
        return "R021"
    elif "400 R031" in log_details:
        return "R031"
    elif "response_code=" in log_details:
        code = re.search(".*response_code=(.*?) ", log_details).group(1)
        if code != "b''":
            return code
    elif "empty encrypted" in log_details:
        return "S000"
    return None


# this is arbitrary, it works well and gives a manageable number of objects on stdout
# and in memory. Modify as needed if you wish so.
DEFAULT_PAGINATION_SIZE = 1000


class PaginatedMigrationCommand(BaseCommand):
    """Generic base command to run paginated work on large querysets.

    Override `queryset` property and `_migrate_object` method.
    """

    queryset = None

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, wet_run=False, **options):
        self.stdout.write(f"paginated migration: queryset objects count={self.queryset.count()}")

        # this is the only efficient way I found to both:
        # - iterate over the objects and treat them on a fire-and-forget basis, without bulk updates.
        # - iterator() and direct filter() cause OOM (out-of-memory) errors.
        # The "bulk update" version, working with chunks, forces us to setup a cron job to run it
        # again and again until exhaustion, and is not really faster.
        paginator = Paginator(self.queryset, DEFAULT_PAGINATION_SIZE)
        try:
            self.stdout.write(f"migration pagination total_range={paginator.page_range}")
            for page_number in paginator.page_range:
                self.stdout.write(f"migration pagination page number={page_number}")
                page = paginator.page(page_number)
                for obj in page.object_list:
                    self._migrate_object(obj, wet_run)
        except KeyboardInterrupt:
            self.stdout.write("! keyboard interrupt, exiting.")

    def _migrate_object(self, obj, wet_run=False, at=None):
        raise NotImplementedError("please override me")


class Command(PaginatedMigrationCommand):
    """This is a one-off command to "migrate" the data contained in the
    JobApplicationPoleEmploiNotificationLog table to the new columns in the Approval table.

    Why I don't do this in a data migration ? Because our migrations are run sequentially,
    during the deployment, by Clever Cloud and should not take too long. I'm expecting
    this migration to be actually quite long since some Python is involved.

    Also this gives us the opportunity to run the migration and stop it whenever we feel like it.
    """

    help = "Migrates the notification data from its dedicated log table to the approvals table."

    queryset = (
        JobApplication.objects.exclude(jobapplicationpoleemploinotificationlog__isnull=True)
        .filter(approval__pe_notification_status=approvals_enums.PEApiNotificationStatus.PENDING)
        .select_related("approval")
        .prefetch_related("jobapplicationpoleemploinotificationlog_set")
    )

    def _migrate_object(self, obj, wet_run=False, at=None):
        job_application = obj
        approval = job_application.approval

        if not approval:
            self.stdout.write(f"> removing logs for job_application={job_application} without approval")
            if wet_run:
                job_application.jobapplicationpoleemploinotificationlog_set.all().delete()
            return

        if job_application.jobapplicationpoleemploinotificationlog_set.filter(
            status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
        ).exists():
            self.stdout.write(
                f"> handling job_application={job_application} approval={approval} as notification success."
            )
            if wet_run:
                approval.pe_save_success(at)
        else:
            for log in job_application.jobapplicationpoleemploinotificationlog_set.order_by("-created_at").all():
                exit_code = exit_code_from_details(log.details)
                if exit_code and approval:
                    endpoint = approvals_enums.PEApiEndpoint.MISE_A_JOUR_PASS_IAE
                    if log.status == JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_SEARCH_INDIVIDUAL:
                        endpoint = approvals_enums.PEApiEndpoint.RECHERCHE_INDIVIDU
                    self.stdout.write(
                        f"> handling job_application={job_application} approval={approval} "
                        f"as notification error exit_code={exit_code}"
                    )
                    if wet_run:
                        approval.pe_save_error(endpoint, exit_code, at)
                    # we found the latest non-recoverable error, stop there
                    break
            else:
                self.stdout.write(
                    f"> handling job_application={job_application} approval={approval} as notification should retry."
                )
                if wet_run:
                    approval.pe_save_should_retry(at)

        # whatever happens, cleanup those logs in order to not go there a second time.
        if wet_run:
            job_application.jobapplicationpoleemploinotificationlog_set.all().delete()
