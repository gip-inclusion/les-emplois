import io

from django.core import management
from django.test import TransactionTestCase

from itou.job_applications import factories as job_application_factories
from itou.job_applications.models import JobApplicationPoleEmploiNotificationLog


class MigratePoleEmploiNotificationLogTestCase(TransactionTestCase):
    def test_ok_log(self):
        job_application = job_application_factories.JobApplicationWithApprovalFactory()
        notification_log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status="ok",
        )
        notification_log.save()
        stdout = io.StringIO()
        management.call_command(
            "migrate_poleemploi_notification_log",
            wet_run=True,
            stdout=stdout,
        )
        stdout.seek(0)
        output = stdout.readlines()
        self.assertEqual(
            output,
            [
                "paginated migration: queryset objects count=1\n",
                "migration pagination total_range=range(1, 2)\n",
                "migration pagination page number=1\n",
                f"> handling job_application={job_application} approval={job_application.approval} "
                "as notification success.\n",
            ],
        )
        self.assertFalse(JobApplicationPoleEmploiNotificationLog.objects.exists())
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_success")

        # run it twice: ensure it does nothing
        stdout = io.StringIO()
        management.call_command(
            "migrate_poleemploi_notification_log",
            wet_run=True,
            stdout=stdout,
        )
        stdout.seek(0)
        output = stdout.readlines()
        self.assertEqual(
            output,
            [
                "paginated migration: queryset objects count=0\n",
                "migration pagination total_range=range(1, 2)\n",
                "migration pagination page number=1\n",
            ],
        )

    def test_ko_log(self):
        job_application = job_application_factories.JobApplicationWithApprovalFactory()
        notification_log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status="search_individual_failure",
            details='   "codeSortie":"FOOBAR2000" ahaha',
        )
        notification_log.save()
        stdout = io.StringIO()
        management.call_command(
            "migrate_poleemploi_notification_log",
            wet_run=True,
            stdout=stdout,
        )
        stdout.seek(0)
        output = stdout.readlines()
        self.assertEqual(
            output,
            [
                "paginated migration: queryset objects count=1\n",
                "migration pagination total_range=range(1, 2)\n",
                "migration pagination page number=1\n",
                f"> handling job_application={job_application} approval={job_application.approval} "
                "as notification error exit_code=FOOBAR2000\n",
            ],
        )
        self.assertFalse(JobApplicationPoleEmploiNotificationLog.objects.exists())
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_error")
        self.assertEqual(job_application.approval.pe_notification_exit_code, "FOOBAR2000")

    def test_retry_log(self):
        job_application = job_application_factories.JobApplicationWithApprovalFactory()
        notification_log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status="search_individual_failure",
            details=" 429 TOO MANY REQUESTS ",
        )
        notification_log.save()
        stdout = io.StringIO()
        management.call_command(
            "migrate_poleemploi_notification_log",
            wet_run=True,
            stdout=stdout,
        )
        stdout.seek(0)
        output = stdout.readlines()
        self.assertEqual(
            output,
            [
                "paginated migration: queryset objects count=1\n",
                "migration pagination total_range=range(1, 2)\n",
                "migration pagination page number=1\n",
                f"> handling job_application={job_application} approval={job_application.approval} "
                "as notification should retry.\n",
            ],
        )
        self.assertFalse(JobApplicationPoleEmploiNotificationLog.objects.exists())
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_should_retry")

    def test_does_nothing_if_already_migrated(self):
        job_application = job_application_factories.JobApplicationWithApprovalFactory()
        # this approval is not pending anymore
        job_application.approval.pe_notification_status = "notification_success"
        job_application.approval.save()
        notification_log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status="ok",
        )
        notification_log.save()
        stdout = io.StringIO()
        management.call_command(
            "migrate_poleemploi_notification_log",
            wet_run=True,
            stdout=stdout,
        )
        stdout.seek(0)
        output = stdout.readlines()
        self.assertEqual(
            output,
            [
                "paginated migration: queryset objects count=0\n",
                "migration pagination total_range=range(1, 2)\n",
                "migration pagination page number=1\n",
            ],
        )
