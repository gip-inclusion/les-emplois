import json
from unittest import mock

from django.conf import settings
from django.core import management
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.mocks.transfer_employee_records import (
    SFTPBadConnectionMock,
    SFTPConnectionMock,
    SFTPEvilConnectionMock,
    SFTPGoodConnectionMock,
)
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, validate_asp_batch_filename
from itou.job_applications.factories import (
    JobApplicationWithApprovalFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
    JobApplicationWithJobSeekerProfileFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.mocks.address_format import mock_get_geocoding_data


class EmployeeRecordModelTest(TestCase):

    fixtures = ["test_INSEE_communes.json"]

    def setUp(self):
        self.employee_record = EmployeeRecordFactory()

    def test_creation_from_job_application(self):
        """
        Employee record objects are created from a job application giving them access to:
        - user / job seeker
        - job seeker profile
        - approval

        Creation is defensive, expect ValidationError if out of the lane
        """
        # Creation with invalid job application state
        with self.assertRaises(AssertionError):
            employee_record = EmployeeRecord.from_job_application(None)

        # Job application is not accepted
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED):
            job_application = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_NEW)
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Job application can be cancelled
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_TOO_RECENT):
            job_application = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Job application has no approval
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_WITHOUT_APPROVAL):
            job_application = JobApplicationWithoutApprovalFactory()
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Job application is duplicated (already existing with same approval and SIAE)
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()

        # Must be ok
        EmployeeRecord.from_job_application(job_application).save()

        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE):
            # Must not
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Job seeker has no existing profile (must be filled before creation)
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_SEEKER_HAS_NO_PROFILE):
            job_application = JobApplicationWithApprovalNotCancellableFactory()
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Job seeker has an incomplete profile
        with self.assertRaises(ValidationError):
            # Message checked in profile tests
            job_application = JobApplicationWithJobSeekerProfileFactory()
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Standard / normal case
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        self.assertIsNotNone(employee_record)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_prepare_successful(self, _mock):
        """
        Mainly format the job seeker address to Hexa format
        """
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        employee_record.update_as_ready()

        job_seeker = job_application.job_seeker
        self.assertIsNotNone(job_seeker.jobseeker_profile)

        # Surface check, this is not a job seeker profile test
        profile = job_seeker.jobseeker_profile
        self.assertIsNotNone(profile.hexa_commune)

    def test_prepare_failed_geoloc(self):
        """
        Test the failure of employee record preparation

        Mainly caused by:
        - geoloc issues (no API mock on this test)
        """
        # Complete profile, but geoloc API not reachable
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()

        with self.assertRaises(ValidationError):
            employee_record = EmployeeRecord.from_job_application(job_application)
            employee_record.update_as_ready()

    def test_batch_filename_validator(self):
        """
        Check format of ASP batch file name
        """
        with self.assertRaises(ValidationError):
            validate_asp_batch_filename(None)

        with self.assertRaises(ValidationError):
            validate_asp_batch_filename("xyz")

        with self.assertRaises(ValidationError):
            validate_asp_batch_filename("RiAE_20210410130000.json")

        validate_asp_batch_filename("RIAE_FS_20210410130000.json")

    def test_find_by_batch(self):
        """
        How to find employee records given their ASP batch file name and line number ?
        """
        filename = "RIAE_FS_20210410130000.json"
        employee_record = EmployeeRecordFactory(asp_batch_file=filename, asp_batch_line_number=2)

        self.assertEqual(EmployeeRecord.objects.find_by_batch("X", 3).count(), 0)
        self.assertEqual(EmployeeRecord.objects.find_by_batch(filename, 3).count(), 0)
        self.assertEqual(EmployeeRecord.objects.find_by_batch("X", 2).count(), 0)

        result = EmployeeRecord.objects.find_by_batch(filename, 2).first()

        self.assertEqual(result.id, employee_record.id)

    def test_archivable(self):
        """
        Check queryset lookup of archived employee records
        """
        filename = "RIAE_FS_20210817130000.json"
        employee_record = EmployeeRecordFactory(
            asp_batch_file=filename,
            asp_batch_line_number=2,
            status=EmployeeRecord.Status.PROCESSED,
            processed_at=timezone.now(),
        )

        # Processed to recently, should not be found
        self.assertEqual(EmployeeRecord.objects.archivable().count(), 0)

        # Fake older date
        employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )

        employee_record.save()

        self.assertEqual(EmployeeRecord.objects.archivable().count(), 1)


class EmployeeRecordBatchTest(TestCase):
    """
    Misc tests on batch wrapper level
    """

    def test_format_feedback_filename(self):
        with self.assertRaises(ValidationError):
            EmployeeRecordBatch.feedback_filename("test.json")

        self.assertEquals(
            "RIAE_FS_20210410130000_FichierRetour.json",
            EmployeeRecordBatch.feedback_filename("RIAE_FS_20210410130000.json"),
        )

    def test_batch_filename_from_feedback(self):
        with self.assertRaises(ValidationError):
            EmployeeRecordBatch.batch_filename_from_feedback("test.json")

        self.assertEqual(
            "RIAE_FS_20210410130000.json",
            EmployeeRecordBatch.batch_filename_from_feedback("RIAE_FS_20210410130000_FichierRetour.json"),
        )


class EmployeeRecordLifeCycleTest(TestCase):
    """
    Note: employee records status is never changed manually
    """

    fixtures = ["test_INSEE_communes.json"]

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def setUp(self, mock):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        self.employee_record = employee_record
        self.employee_record.update_as_ready()

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_ready(self, _mock):
        self.assertEqual(self.employee_record.status, EmployeeRecord.Status.READY)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_sent(self, _mock):
        filename = "RIAE_FS_20210410130000.json"
        self.employee_record.update_as_sent(filename, 1)

        self.assertEqual(filename, self.employee_record.asp_batch_file)
        self.assertEqual(self.employee_record.status, EmployeeRecord.Status.SENT)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_rejected(self, _mock):
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)

        err_code, err_message = "12", "JSON Invalide"

        self.employee_record.update_as_rejected(err_code, err_message)
        self.assertEqual(self.employee_record.status, EmployeeRecord.Status.REJECTED)
        self.assertEqual(self.employee_record.asp_processing_code, err_code)
        self.assertEqual(self.employee_record.asp_processing_label, err_message)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_processed(self, _mock):
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)

        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_accepted(process_code, process_message, "{}")

        self.assertEqual(self.employee_record.status, EmployeeRecord.Status.PROCESSED)
        self.assertEqual(self.employee_record.asp_processing_code, process_code)
        self.assertEqual(self.employee_record.asp_processing_label, process_message)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_archived(self, _mock):
        filename = "RIAE_FS_20210816130001.json"
        self.employee_record.update_as_sent(filename, 1)

        # No processing date at the moment
        self.assertIsNone(self.employee_record.processed_at)

        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_accepted(process_code, process_message, "{}")

        # Can't archive, too recent
        with self.assertRaises(ValidationError):
            self.employee_record.update_as_archived()

        # Fake old date, but not to old
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS - 1
        )

        with self.assertRaises(ValidationError):
            self.employee_record.update_as_archived()

        # Fake a date older than archiving delay
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )

        self.employee_record.update_as_archived()

        # Check correct status and empty archived JSON
        self.assertEqual(self.employee_record.status, EmployeeRecord.Status.ARCHIVED)
        self.assertIsNone(self.employee_record.archived_json)


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

        self.assertEqual(employee_record.status, EmployeeRecord.Status.READY)

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

        self.assertEqual(employee_record.status, EmployeeRecord.Status.READY)

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_upload_failure(self):
        employee_record = self.employee_record
        with self.assertRaises(Exception):
            management.call_command("transfer_employee_records", upload=True)

        self.assertEqual(employee_record.status, EmployeeRecord.Status.READY)

    @mock.patch("pysftp.Connection", SFTPBadConnectionMock)
    def test_download_failure(self):
        employee_record = self.employee_record
        with self.assertRaises(Exception):
            management.call_command("transfer_employee_records", download=True)

        self.assertEqual(employee_record.status, EmployeeRecord.Status.READY)

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

        self.assertEqual(employee_record.status, EmployeeRecord.Status.SENT)
        self.assertEqual(employee_record.batch_line_number, 1)
        self.assertIsNotNone(employee_record.asp_batch_file)

        management.call_command("transfer_employee_records", upload=False, download=True)
        employee_record.refresh_from_db()

        self.assertEqual(employee_record.status, EmployeeRecord.Status.PROCESSED)
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

        self.assertEqual(EmployeeRecord.Status.PROCESSED, employee_record.status)
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
        self.assertEqual(employee_record.status, EmployeeRecord.Status.READY)

        for _ in range(10):
            with self.assertRaises(Exception):
                management.call_command("transfer_employee_records", upload=False, download=True)

        employee_record.refresh_from_db()
        self.assertEqual(employee_record.status, EmployeeRecord.Status.READY)

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_archive(self, _mock):
        """
        Check archiving old processed employee records
        """
        # Create an old PROCESSED employee record
        filename = "RIAE_FS_20210819100001.json"
        self.employee_record.update_as_sent(filename, 1)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_accepted(process_code, process_message, "{}")

        # Fake a date older than archiving delay
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )

        self.employee_record.update_as_archived()

        # Nicer syntax:
        management.call_command("transfer_employee_records", archive=True)

        self.employee_record.refresh_from_db()

        # Check correct status and empty archived JSON
        self.assertEqual(self.employee_record.status, EmployeeRecord.Status.ARCHIVED)
        self.assertIsNone(self.employee_record.archived_json)
