import json
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.core import management
from django.test import TestCase
from django.utils import timezone

from itou.employee_record.enums import Status
from itou.employee_record.mocks.transfer_employee_records import (
    SFTPBadConnectionMock,
    SFTPConnectionMock,
    SFTPEvilConnectionMock,
    SFTPGoodConnectionMock,
)
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from itou.utils.mocks.address_format import mock_get_geocoding_data


# There is no need to create 700 employee records for a single batch
# so this class var is changed to 1 for tests, otherwise download operation is not triggered.
@mock.patch("itou.employee_record.models.EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS", new=1)
class EmployeeRecordManagementCommandTest(TestCase):
    """
    Employee record management command, testing:
    - mocked sftp connection
    - basic upload / download modes
    - ...
    """

    fixtures = ["test_INSEE_communes.json", "test_asp_INSEE_countries.json"]

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
        management.call_command("transfer_employee_records", download=True)

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_upload(self):
        management.call_command("transfer_employee_records", upload=True)

    @mock.patch("pysftp.Connection", SFTPConnectionMock)
    def test_smoke_download_and_upload(self):
        management.call_command("transfer_employee_records")

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_dryrun_upload(self, _mock):
        employee_record = self.employee_record

        # Upload with dry run
        management.call_command("transfer_employee_records", upload=True, dry_run=True)

        # Then download "for real", should work but leave
        # employee record untouched
        management.call_command("transfer_employee_records", upload=False, download=True)

        self.assertEqual(employee_record.status, Status.READY)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_dryrun_download(self, _mock):
        employee_record = self.employee_record

        # Upload "for real"
        management.call_command("transfer_employee_records", upload=True)

        # Then download dry run, should work but leave
        # employee record untouched
        management.call_command("transfer_employee_records", upload=False, download=True, dry_run=True)

        self.assertEqual(employee_record.status, Status.READY)

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_upload_failure(self):
        employee_record = self.employee_record
        with self.assertRaises(Exception):
            management.call_command("transfer_employee_records", upload=True)

        self.assertEqual(employee_record.status, Status.READY)

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_download_failure(self):
        employee_record = self.employee_record
        with self.assertRaises(Exception):
            management.call_command("transfer_employee_records", download=True)

        self.assertEqual(employee_record.status, Status.READY)

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

        management.call_command("transfer_employee_records", upload=True, download=False)
        employee_record.refresh_from_db()

        self.assertEqual(employee_record.status, Status.SENT)
        self.assertEqual(employee_record.batch_line_number, 1)
        self.assertIsNotNone(employee_record.asp_batch_file)

        management.call_command("transfer_employee_records", upload=False, download=True)
        employee_record.refresh_from_db()

        self.assertEqual(employee_record.status, Status.PROCESSED)
        self.assertEqual(employee_record.asp_processing_code, "0000")

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

        management.call_command("transfer_employee_records", upload=True, download=True)
        employee_record.refresh_from_db()

        self.assertEqual(Status.PROCESSED, employee_record.status)
        self.assertIsNotNone(employee_record.archived_json)

        employee_record_json = json.loads(employee_record.archived_json)

        self.assertEqual("0000", employee_record_json.get("codeTraitement"))
        self.assertIsNotNone(employee_record_json.get("libelleTraitement"))

    @mock.patch("pysftp.Connection", SFTPEvilConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_random_connection_failure(self, _mock):
        employee_record = self.employee_record

        # Random upload failure
        for _ in range(10):
            with self.assertRaises(Exception):
                management.call_command("transfer_employee_records", upload=True, download=False)

        # Employee record must be in the same status
        employee_record.refresh_from_db()
        self.assertEqual(employee_record.status, Status.READY)

        for _ in range(10):
            with self.assertRaises(Exception):
                management.call_command("transfer_employee_records", upload=False, download=True)

        employee_record.refresh_from_db()
        self.assertEqual(employee_record.status, Status.READY)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_archive_employee_records(self, _mock):
        """
        Check archiving old processed employee records
        """
        # Create an old PROCESSED employee record
        filename = "RIAE_FS_20210819100001.json"
        self.employee_record.update_as_sent(filename, 1)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_processed(process_code, process_message, "{}")

        # Fake a date older than archiving delay
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )

        self.employee_record.update_as_archived()

        # Nicer syntax:
        management.call_command("transfer_employee_records", archive=True)

        self.employee_record.refresh_from_db()

        # Check correct status and empty archived JSON
        self.assertEqual(self.employee_record.status, Status.ARCHIVED)
        self.assertIsNone(self.employee_record.archived_json)


class JobApplicationConstraintsTest(TestCase):
    """
    Check constraints between job applications and employee records
    """

    fixtures = ["test_INSEE_communes.json", "test_asp_INSEE_countries.json"]

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def setUp(self, _mock):
        # Make job application cancellable
        hiring_date = date.today() + timedelta(days=7)

        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(hiring_start_at=hiring_date)
        self.employee_record = EmployeeRecord.from_job_application(self.job_application)
        self.employee_record.update_as_ready()

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_job_application_is_cancellable(self, _mock):
        # A job application can be cancelled only if there is no
        # linked employee records with ACCEPTED or SENT status

        # status is READY
        self.assertTrue(self.job_application.can_be_cancelled)

        # status is SENT
        filename = "RIAE_FS_20210410130000.json"
        self.employee_record.update_as_sent(filename, 1)
        self.assertFalse(self.job_application.can_be_cancelled)

        # status is REJECTED
        err_code, err_message = "12", "JSON Invalide"
        self.employee_record.update_as_rejected(err_code, err_message)
        self.assertTrue(self.job_application.can_be_cancelled)

        # status is PROCESSED
        self.employee_record.update_as_ready()
        self.employee_record.update_as_sent(filename, 1)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_processed(process_code, process_message, "{}")
        self.assertFalse(self.job_application.can_be_cancelled)
