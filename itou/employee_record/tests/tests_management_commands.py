import json
from unittest import mock

from django.conf import settings
from django.core import management
from django.utils import timezone

from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordFactory, EmployeeRecordWithProfileFactory
from itou.employee_record.mocks.transfer_employee_records import (
    SFTPBadConnectionMock,
    SFTPConnectionMock,
    SFTPEvilConnectionMock,
    SFTPGoodConnectionMock,
)
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from itou.utils.mocks.address_format import mock_get_geocoding_data

from ._common import ManagementCommandTestCase


# There is no need to create 700 employee records for a single batch
# so this class var is changed to 1 for tests, otherwise download operation is not triggered.
@mock.patch("itou.employee_record.models.EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS", new=1)
class TransferManagementCommandTest(ManagementCommandTestCase):
    """
    Employee record management command, testing:
    - mocked sftp connection
    - basic upload / download modes
    - ...
    """

    fixtures = ["test_INSEE_communes.json", "test_asp_INSEE_countries.json"]

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


class SanitizeManagementCommandTest(ManagementCommandTestCase):

    MANAGEMENT_COMMAND_NAME = "sanitize_employee_records"

    fixtures = ["test_INSEE_communes.json", "test_asp_INSEE_countries.json"]

    def test_dry_run(self):
        # Check `dry-run` switch / option
        dry_run_msg = " - DRY-RUN mode: not fixing, just reporting"

        # On:
        out, _ = self.call_command()
        self.assertNotIn(out, dry_run_msg)

        # Off:
        out, _ = self.call_command(dry_run=True)
        self.assertIn(dry_run_msg, out)
        self.assertNotIn(" - done!", out)

    def test_3436_errors_check(self):
        # Check for 3436 errors fix (ASP duplicates)

        # Note: must be created with a valid profile, or the profile check will disable it beforehand
        EmployeeRecordWithProfileFactory(
            status=Status.REJECTED,
            asp_processing_code=EmployeeRecord.DUPLICATE_ASP_ERROR_CODE,
        )
        self.assertEqual(1, EmployeeRecord.objects.asp_duplicates().count())

        out, _ = self.call_command()

        # Exterminate 3436s
        self.assertIn(" - fixing 3436 errors: forcing status to PROCESSED", out)
        self.assertIn(" - done!", out)
        self.assertEqual(0, EmployeeRecord.objects.asp_duplicates().count())

    def test_orphans_check(self):
        # Check if any orphan (mismatch in `asp_id`)

        # TODO: Simple way to create an orphan but would a factory be better ?
        # Note: must be created with a valid profile, or the profile check will disable it beforehand
        orphan_employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        orphan_employee_record.asp_id += 1
        orphan_employee_record.save()

        self.assertEqual(1, EmployeeRecord.objects.orphans().count())

        out, _ = self.call_command()

        self.assertIn(" - fixing orphans: switching status to DISABLED", out)
        self.assertIn(" - done!", out)
        self.assertEqual(0, EmployeeRecord.objects.orphans().count())

    def test_profile_errors_check(self):
        # Check for profile errors

        # This factory does not define a profile
        EmployeeRecordFactory()

        out, _ = self.call_command()

        self.assertIn(" - fixing missing jobseeker profiles: switching status to DISABLED", out)
        self.assertIn(" - done!", out)
