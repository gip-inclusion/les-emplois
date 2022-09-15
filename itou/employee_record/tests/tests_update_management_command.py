from unittest import mock

from django.test import override_settings

import itou.employee_record.enums as er_enums
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.factories import EmployeeRecordUpdateNotificationFactory
from itou.employee_record.mocks.transfer_employee_records import SFTPGoodConnectionMock
from itou.employee_record.models import EmployeeRecordUpdateNotification

from .common import ManagementCommandTestCase


@override_settings(ASP_FS_SFTP_HOST="foobar.com", ASP_FS_SFTP_USER="django_tests")
class TransferUpdatesManagementCommandTest(ManagementCommandTestCase):

    MANAGEMENT_COMMAND_NAME = "transfer_employee_records_updates"

    def setUp(self):
        self.notification = EmployeeRecordUpdateNotificationFactory()

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_dry_run_upload(self):
        out, _ = self.call_command(upload=True, download=False)

        self.assertIn("DRY-RUN mode", out)
        self.assertIn("Connected to:", out)
        self.assertIn("Current remote dir is:", out)
        self.assertIn("Starting UPLOAD", out)
        self.assertIn("DRY-RUN: (not) sending", out)
        self.assertIn("Employee record notifications processing done", out)

        self.notification.refresh_from_db()
        self.assertEqual(er_enums.NotificationStatus.NEW, self.notification.status)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_upload(self):
        out, _ = self.call_command(upload=True, download=False, wet_run=True)

        self.assertNotIn("DRY-RUN mode", out)
        self.assertIn("Connected to:", out)
        self.assertIn("Current remote dir is:", out)
        self.assertIn("Starting UPLOAD", out)
        self.assertNotIn("DRY-RUN: (not) sending", out)
        self.assertNotIn("DRY-RUN: Not updating notification status", out)
        self.assertIn("Employee record notifications processing done", out)

        self.notification.refresh_from_db()
        self.assertEqual(er_enums.NotificationStatus.SENT, self.notification.status)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_dry_run_empty_download(self):
        out, _ = self.call_command(upload=False, download=True)

        self.assertIn("DRY-RUN mode", out)
        self.assertIn("Connected to:", out)
        self.assertIn("Current remote dir is:", out)
        self.assertIn("Starting DOWNLOAD", out)
        self.assertIn("Employee record notifications processing done", out)

        self.notification.refresh_from_db()
        self.assertEqual(er_enums.NotificationStatus.NEW, self.notification.status)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_download(self):
        out, _ = self.call_command(upload=False, download=True, wet_run=True)

        self.assertNotIn("DRY-RUN mode", out)
        self.assertIn("Connected to:", out)
        self.assertIn("Current remote dir is:", out)
        self.assertIn("Starting DOWNLOAD", out)
        self.assertIn("Employee record notifications processing done", out)

        # TODO: implement SFTP mock with fake result file

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_asp_test(self):
        out, _ = self.call_command(upload=False, download=False, test=True, wet_run=True)

        self.assertIn("Using *TEST* JSON serializers", out)

    @override_settings(ASP_FS_SFTP_HOST="")
    def test_wrong_environment(self):
        out, _ = self.call_command(upload=False, download=False, wet_run=True)

        self.assertIn("Your environment is missing ASP_FS_SFTP_HOST to run this command.", out)

    # Next part is about testing --preflight option,
    # which is common to all `EmployeeRecordTransferCommand` subclasses.
    # There's no need to duplicate and test all subclasses
    # (such as the management command for employee record transfers).

    def test_preflight_without_object(self):
        # Test --preflight option if there is no object ready to be transfered.
        EmployeeRecordUpdateNotification.objects.all().delete()
        out, _ = self.call_command(preflight=True)

        self.assertFalse(EmployeeRecordUpdateNotification.objects.new())
        self.assertIn("Preflight activated, checking for possible serialization errors...", out)
        self.assertIn("No object to check. Exiting preflight.", out)

    def test_preflight_without_error(self):
        # Test --preflight option if all objects ready to be transfered
        # have a correct JSON structure.
        out, _ = self.call_command(preflight=True)

        self.assertIn("Preflight activated, checking for possible serialization errors...", out)
        self.assertIn("All serializations ok, you may skip preflight...", out)

    def test_preflight_with_error(self):
        # Test --preflight option with an object ready to be transfered,
        # but with an incorrect JSON structure.

        # Create a notification with a bad structure : no HEXA address
        bad_notification = EmployeeRecordUpdateNotificationFactory()
        # Beware of 1:1 objects auto-update when not at top level
        # (i.e. don't do: bad_notification.employee_record.job_seeker.jobseeker_profile.hexa_commune = None).
        profile = bad_notification.employee_record.job_seeker.jobseeker_profile
        profile.hexa_commune = None
        profile.save()

        with self.assertRaises(SerializationError):
            self.call_command(preflight=True)
