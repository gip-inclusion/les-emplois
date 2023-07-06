from unittest import mock

import freezegun
from django.test import override_settings

import itou.employee_record.enums as er_enums
from itou.employee_record.mocks.transfer_employee_records import SFTPGoodConnectionMock
from itou.employee_record.models import EmployeeRecordUpdateNotification
from tests.employee_record.common import ManagementCommandTestCase
from tests.employee_record.factories import EmployeeRecordUpdateNotificationFactory


@override_settings(ASP_FS_SFTP_HOST="foobar.com", ASP_FS_SFTP_USER="django_tests")
class TransferUpdatesManagementCommandTest(ManagementCommandTestCase):

    MANAGEMENT_COMMAND_NAME = "transfer_employee_records_updates"

    @classmethod
    def setUpTestData(cls):
        cls.notification = EmployeeRecordUpdateNotificationFactory()

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_dry_run_upload(self):
        self.call_command(upload=True)

        self.notification.refresh_from_db()
        assert er_enums.NotificationStatus.NEW == self.notification.status

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_upload(self):
        with freezegun.freeze_time("2021-09-27"):
            out, _ = self.call_command(upload=True, wet_run=True)
        assert out == self.snapshot

        self.notification.refresh_from_db()
        assert er_enums.NotificationStatus.SENT == self.notification.status

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_dry_run_empty_download(self):
        out, _ = self.call_command(download=True)
        assert out == self.snapshot

        self.notification.refresh_from_db()
        assert er_enums.NotificationStatus.NEW == self.notification.status

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_download(self):
        with freezegun.freeze_time("2021-09-27"):
            out, _ = self.call_command(upload=True, wet_run=True)
        assert out == self.snapshot(name="upload")

        self.notification.refresh_from_db()
        assert self.notification.status == er_enums.Status.SENT
        assert self.notification.asp_batch_line_number == 1
        assert self.notification.asp_batch_file is not None
        assert self.notification.archived_json
        assert self.notification.archived_json["codeTraitement"] is None

        out, _ = self.call_command(download=True, wet_run=True)
        assert out == self.snapshot(name="download")

        self.notification.refresh_from_db()
        assert self.notification.status == er_enums.Status.PROCESSED
        assert self.notification.asp_processing_code == EmployeeRecordUpdateNotification.ASP_PROCESSING_SUCCESS_CODE
        assert self.notification.archived_json
        assert self.notification.archived_json["codeTraitement"] == self.notification.asp_processing_code

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_asp_test(self):
        out, _ = self.call_command(test=True, download=True, wet_run=True)
        assert out == self.snapshot

    @override_settings(ASP_FS_SFTP_HOST="")
    def test_wrong_environment(self):
        out, _ = self.call_command(download=True, wet_run=True)
        assert out == self.snapshot

    # Next part is about testing --preflight option,
    # which is common to all `EmployeeRecordTransferCommand` subclasses.
    # There's no need to duplicate and test all subclasses
    # (such as the management command for employee record transfers).

    def test_preflight_without_object(self):
        # Test --preflight option if there is no object ready to be transferred.
        EmployeeRecordUpdateNotification.objects.all().delete()

        out, _ = self.call_command(preflight=True)
        assert out == self.snapshot

        assert not EmployeeRecordUpdateNotification.objects.filter(status=er_enums.NotificationStatus.NEW)

    def test_preflight_without_error(self):
        # Test --preflight option if all objects ready to be transferred
        # have a correct JSON structure.
        out, _ = self.call_command(preflight=True)
        assert out == self.snapshot

    def test_preflight_with_error(self):
        # Test --preflight option with an object ready to be transferred,
        # but with an incorrect JSON structure.

        # Create a notification with a bad structure : no HEXA address
        bad_notification = EmployeeRecordUpdateNotificationFactory(pk=42)
        # Beware of 1:1 objects auto-update when not at top level
        # (i.e. don't do: bad_notification.employee_record.job_seeker.jobseeker_profile.hexa_commune = None).
        profile = bad_notification.employee_record.job_seeker.jobseeker_profile
        profile.hexa_commune = None
        profile.save()

        out, _ = self.call_command(preflight=True)
        assert out == self.snapshot
