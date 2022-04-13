from io import StringIO
from unittest import mock

from django.core import management
from django.test import TestCase
from django.test.utils import override_settings

import itou.employee_record.enums as er_enums
from itou.employee_record.factories import EmployeeRecordUpdateNotificationFactory
from itou.employee_record.mocks.transfer_employee_records import SFTPGoodConnectionMock


class EmployeeRecordUpdatesManagementCommandTest(TestCase):
    def setUp(self):
        self.notification = EmployeeRecordUpdateNotificationFactory()

    def call_command(self, *args, **kwargs):
        out = StringIO()
        err = StringIO()
        management.call_command(
            "transfer_employee_records_updates",
            *args,
            stdout=out,
            stderr=err,
            **kwargs,
        )
        return out.getvalue(), err.getvalue()

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_dry_run_upload(self):
        out, _ = self.call_command(upload=True, download=False, dry_run=True)

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
        out, _ = self.call_command(upload=True, download=False)

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
        out, _ = self.call_command(upload=False, download=True, dry_run=True)

        self.assertIn("DRY-RUN mode", out)
        self.assertIn("Connected to:", out)
        self.assertIn("Current remote dir is:", out)
        self.assertIn("Starting DOWNLOAD", out)
        self.assertIn("Employee record notifications processing done", out)

        self.notification.refresh_from_db()
        self.assertEqual(er_enums.NotificationStatus.NEW, self.notification.status)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_download(self):
        out, _ = self.call_command(upload=False, download=True)

        self.assertNotIn("DRY-RUN mode", out)
        self.assertIn("Connected to:", out)
        self.assertIn("Current remote dir is:", out)
        self.assertIn("Starting DOWNLOAD", out)
        self.assertIn("Employee record notifications processing done", out)

        # TODO: implement SFTP mock with fake result file

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_asp_test(self):
        out, _ = self.call_command(upload=False, download=False, test=True)

        self.assertIn("Using *TEST* JSON serializers", out)

    @override_settings(EMPLOYEE_RECORD_TRANSFER_ENABLED=False)
    def test_wrong_environment(self):
        out, _ = self.call_command(upload=False, download=False)

        self.assertIn("Update Django settings if needed.", out)
