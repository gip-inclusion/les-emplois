from unittest import mock

import pytest
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

        assert "DRY-RUN mode" in out
        assert "Connected to:" in out
        assert "Current remote dir is:" in out
        assert "Starting UPLOAD" in out
        assert "DRY-RUN: (not) sending" in out
        assert "Employee record notifications processing done" in out

        self.notification.refresh_from_db()
        assert er_enums.NotificationStatus.NEW == self.notification.status

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_upload(self):
        out, _ = self.call_command(upload=True, download=False, wet_run=True)

        assert "DRY-RUN mode" not in out
        assert "Connected to:" in out
        assert "Current remote dir is:" in out
        assert "Starting UPLOAD" in out
        assert "DRY-RUN: (not) sending" not in out
        assert "DRY-RUN: Not updating notification status" not in out
        assert "Employee record notifications processing done" in out

        self.notification.refresh_from_db()
        assert er_enums.NotificationStatus.SENT == self.notification.status

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_dry_run_empty_download(self):
        out, _ = self.call_command(upload=False, download=True)

        assert "DRY-RUN mode" in out
        assert "Connected to:" in out
        assert "Current remote dir is:" in out
        assert "Starting DOWNLOAD" in out
        assert "Employee record notifications processing done" in out

        self.notification.refresh_from_db()
        assert er_enums.NotificationStatus.NEW == self.notification.status

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_download(self):
        self.call_command(upload=True, wet_run=True)
        self.notification.refresh_from_db()
        assert self.notification.status == er_enums.Status.SENT
        assert self.notification.asp_batch_line_number == 1
        assert self.notification.asp_batch_file is not None
        assert self.notification.archived_json
        assert self.notification.archived_json["codeTraitement"] is None

        out, _ = self.call_command(download=True, wet_run=True)

        assert "DRY-RUN mode" not in out
        assert "Connected to:" in out
        assert "Current remote dir is:" in out
        assert "Starting DOWNLOAD" in out
        assert "Employee record notifications processing done" in out

        self.notification.refresh_from_db()
        assert self.notification.status == er_enums.Status.PROCESSED
        assert self.notification.asp_processing_code == EmployeeRecordUpdateNotification.ASP_PROCESSING_SUCCESS_CODE
        assert self.notification.archived_json
        assert self.notification.archived_json["codeTraitement"] == self.notification.asp_processing_code

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_asp_test(self):
        out, _ = self.call_command(upload=False, download=False, test=True, wet_run=True)

        assert "Using *TEST* JSON serializers" in out

    @override_settings(ASP_FS_SFTP_HOST="")
    def test_wrong_environment(self):
        out, _ = self.call_command(upload=False, download=False, wet_run=True)

        assert "Your environment is missing ASP_FS_SFTP_HOST to run this command." in out

    # Next part is about testing --preflight option,
    # which is common to all `EmployeeRecordTransferCommand` subclasses.
    # There's no need to duplicate and test all subclasses
    # (such as the management command for employee record transfers).

    def test_preflight_without_object(self):
        # Test --preflight option if there is no object ready to be transfered.
        EmployeeRecordUpdateNotification.objects.all().delete()
        out, _ = self.call_command(preflight=True)

        assert not EmployeeRecordUpdateNotification.objects.new()
        assert "Preflight activated, checking for possible serialization errors..." in out
        assert "No object to check. Exiting preflight." in out

    def test_preflight_without_error(self):
        # Test --preflight option if all objects ready to be transfered
        # have a correct JSON structure.
        out, _ = self.call_command(preflight=True)

        assert "Preflight activated, checking for possible serialization errors..." in out
        assert "All serializations ok, you may skip preflight..." in out

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

        with pytest.raises(SerializationError):
            self.call_command(preflight=True)
