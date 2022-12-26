from unittest import mock

import pytest
from django.test.utils import override_settings
from django.utils import timezone

from itou.employee_record import constants
from itou.employee_record.enums import NotificationType, Status
from itou.employee_record.mocks.transfer_employee_records import (
    SFTPAllDupsConnectionMock,
    SFTPBadConnectionMock,
    SFTPConnectionMock,
    SFTPEvilConnectionMock,
    SFTPGoodConnectionMock,
)
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from itou.utils.mocks.address_format import mock_get_geocoding_data

from ...approvals.factories import ProlongationFactory, SuspensionFactory
from .common import ManagementCommandTestCase


# There is no need to create 700 employee records for a single batch
# so this class var is changed to 1 for tests, otherwise download operation is not triggered.
@mock.patch("itou.employee_record.models.EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS", new=1)
@override_settings(ASP_FS_SFTP_HOST="foobar.com", ASP_FS_SFTP_USER="django_tests")
class EmployeeRecordManagementCommandTest(ManagementCommandTestCase):
    """
    Employee record management command, testing:
    - mocked sftp connection
    - basic upload / download modes
    - ...
    """

    MANAGEMENT_COMMAND_NAME = "transfer_employee_records"

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def setUp(self, _mock):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        employee_record.update_as_ready()
        self.employee_record = employee_record
        self.job_application = job_application

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_download(self):
        self.call_command(download=True)

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_upload(self):
        self.call_command(upload=True)

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_download_and_upload(self):
        self.call_command()

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_dryrun_upload(self, _mock):
        employee_record = self.employee_record

        # Upload with dry run
        self.call_command(upload=True, dry_run=True)

        # Then download "for real", should work but leave
        # employee record untouched
        self.call_command(upload=False, download=True)

        assert employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_dryrun_download(self, _mock):
        employee_record = self.employee_record

        # Upload "for real"
        self.call_command(upload=True)

        # Then download dry run, should work but leave
        # employee record untouched
        self.call_command(upload=False, download=True, dry_run=True)

        assert employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_upload_failure(self):
        employee_record = self.employee_record
        with pytest.raises(Exception):
            self.call_command(upload=True)

        assert employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_download_failure(self):
        employee_record = self.employee_record
        with pytest.raises(Exception):
            self.call_command(download=True)

        assert employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_upload_and_download_success(self, _mock):
        """
        - Create an employee record
        - Send it to ASP
        - Get feedback
        - Update employee record
        """
        employee_record = self.employee_record

        self.call_command(upload=True, download=False)
        employee_record.refresh_from_db()

        assert employee_record.status == Status.SENT
        assert employee_record.batch_line_number == 1
        assert employee_record.asp_batch_file is not None

        self.call_command(upload=False, download=True)
        employee_record.refresh_from_db()

        assert employee_record.status == Status.PROCESSED
        assert employee_record.asp_processing_code == EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_employee_record_proof(self, _mock):
        """
        Check that "proof" of validated employee record is OK
        """
        employee_record = self.employee_record

        self.call_command(upload=True, download=True)
        employee_record.refresh_from_db()

        assert Status.PROCESSED == employee_record.status
        assert employee_record.archived_json is not None

        assert EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE == employee_record.archived_json.get("codeTraitement")
        assert employee_record.archived_json.get("libelleTraitement") is not None

    @mock.patch("pysftp.Connection", SFTPEvilConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_random_connection_failure(self, _mock):
        employee_record = self.employee_record

        # Random upload failure
        for _ in range(10):
            with pytest.raises(Exception):
                self.call_command(upload=True, download=False)

        # Employee record must be in the same status
        employee_record.refresh_from_db()
        assert employee_record.status == Status.READY

        for _ in range(10):
            with pytest.raises(Exception):
                self.call_command(upload=False, download=True)

        employee_record.refresh_from_db()
        assert employee_record.status == Status.READY

    def test_archive_employee_records(self):
        """
        Check archiving old processed employee records
        """

        # Fake a date older than archiving delay
        self.employee_record.status = Status.PROCESSED
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=constants.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )
        self.employee_record.save()

        self.call_command(archive=True)
        self.employee_record.refresh_from_db()

        # Check correct status and empty archived JSON
        assert self.employee_record.status == Status.ARCHIVED
        assert self.employee_record.archived_json is None

    @mock.patch("pysftp.Connection", SFTPAllDupsConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_automatic_duplicates_processing(self, _):
        # Check that from now on employee records with a 3436 processing code
        # are auto-magically converted as PROCESSED employee records

        # Don't forget to make a complete upload / download cycle
        self.call_command(upload=True, download=True)

        self.employee_record.refresh_from_db()

        assert 0 == EmployeeRecord.objects.asp_duplicates().count()
        assert Status.PROCESSED == self.employee_record.status
        assert self.employee_record.processed_as_duplicate

    @mock.patch("pysftp.Connection", SFTPAllDupsConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_duplicates_with_a_suspension_generate_an_update_notification(self, _):
        SuspensionFactory(approval=self.employee_record.job_application.approval)

        # Don't forget to make a complete upload / download cycle
        self.call_command(upload=True, download=True)

        self.employee_record.refresh_from_db()

        assert self.employee_record.update_notifications.count() == 1
        assert self.employee_record.update_notifications.first().notification_type == NotificationType.APPROVAL

    @mock.patch("pysftp.Connection", SFTPAllDupsConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_duplicates_with_a_prolongation_generate_an_update_notification(self, _):
        ProlongationFactory(approval=self.employee_record.job_application.approval)

        # Don't forget to make a complete upload / download cycle
        self.call_command(upload=True, download=True)

        self.employee_record.refresh_from_db()

        assert self.employee_record.update_notifications.count() == 1
        assert self.employee_record.update_notifications.first().notification_type == NotificationType.APPROVAL
