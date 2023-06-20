from unittest import mock

import freezegun
import pytest
from django.test.utils import override_settings

from itou.employee_record.enums import Status
from itou.employee_record.mocks.transfer_employee_records import (
    SFTPAllDupsConnectionMock,
    SFTPBadConnectionMock,
    SFTPConnectionMock,
    SFTPEvilConnectionMock,
    SFTPGoodConnectionMock,
)
from itou.employee_record.models import EmployeeRecord
from itou.utils.mocks.address_format import mock_get_geocoding_data
from tests.approvals.factories import ProlongationFactory, SuspensionFactory
from tests.employee_record.common import ManagementCommandTestCase
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory


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

    @classmethod
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def setUpTestData(cls, _mock):
        cls.job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        cls.employee_record = EmployeeRecord.from_job_application(cls.job_application)
        cls.employee_record.update_as_ready()

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_download(self):
        out, _ = self.call_command(download=True)
        assert out == self.snapshot

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_upload(self):
        with freezegun.freeze_time("2021-09-27"):
            out, _ = self.call_command(upload=True)
        assert out == self.snapshot

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_download_and_upload(self):
        with freezegun.freeze_time("2021-09-27"):
            out, _ = self.call_command(upload=True, download=True)
        assert out == self.snapshot

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_dry_run_upload_and_download(self, _mock):
        self.call_command(upload=True, download=True, dry_run=True)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_upload_failure(self):
        with pytest.raises(Exception):
            self.call_command(upload=True)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_download_failure(self):
        with pytest.raises(Exception):
            self.call_command(download=True)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

    @mock.patch("pysftp.Connection", SFTPEvilConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_random_connection_failure(self, _mock):
        employee_record = self.employee_record

        # Random upload failure
        with pytest.raises(Exception):
            self.call_command(upload=True)
        # Employee record must be in the same status
        employee_record.refresh_from_db()
        assert employee_record.status == Status.READY

        with pytest.raises(Exception):
            self.call_command(download=True)
        # Employee record must be in the same status
        employee_record.refresh_from_db()
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

        with freezegun.freeze_time("2021-09-27"):
            out, _ = self.call_command(upload=True)
        assert out == self.snapshot(name="upload")

        employee_record.refresh_from_db()
        assert employee_record.status == Status.SENT
        assert employee_record.asp_batch_line_number == 1
        assert employee_record.asp_batch_file is not None

        out, _ = self.call_command(download=True)
        assert out == self.snapshot(name="download")

        employee_record.refresh_from_db()
        assert employee_record.status == Status.PROCESSED
        assert employee_record.asp_processing_code == EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE
        assert (
            employee_record.archived_json.get("libelleTraitement")
            == "La ligne de la fiche salarié a été enregistrée avec succès."
        )

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    def test_asp_test(self):
        out, _ = self.call_command(test=True, download=True)
        assert out == self.snapshot

    @override_settings(ASP_FS_SFTP_HOST="")
    def test_wrong_environment(self):
        out, _ = self.call_command(download=True)
        assert out == self.snapshot

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
