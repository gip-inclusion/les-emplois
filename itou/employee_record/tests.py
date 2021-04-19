from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.management.commands.transfer_employee_records import Command
from itou.employee_record.mocks.transfer_employee_records import SFTPConnectionMock, SFTPGoodConnectionMock
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
        # Creation with invalid job application sate
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
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE):
            job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
            # Must be ok
            EmployeeRecord.from_job_application(job_application).save()
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
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_prepare_successful(self, _mock):
        """
        Mainly format the job seeker address to Hexa format
        """
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        employee_record.prepare()

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
            employee_record.prepare()

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

        self.assertEquals(EmployeeRecord.objects.find_by_batch("X", 3).count(), 0)
        self.assertEquals(EmployeeRecord.objects.find_by_batch(filename, 3).count(), 0)
        self.assertEquals(EmployeeRecord.objects.find_by_batch("X", 2).count(), 0)

        result = EmployeeRecord.objects.find_by_batch(filename, 2).first()

        self.assertEquals(result.id, employee_record.id)


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

        self.assertEquals(
            "RIAE_FS_20210410130000.json",
            EmployeeRecordBatch.batch_filename_from_feedback("RIAE_FS_20210410130000_FichierRetour.json"),
        )


class EmployeeRecordLifeCycleTest(TestCase):
    """
    Employee record status is never changed manually
    """

    fixtures = ["test_INSEE_communes.json"]

    def setUp(self):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        self.employee_record = employee_record

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_ready(self, _mock):
        self.employee_record.prepare()
        self.assertEquals(self.employee_record.status, EmployeeRecord.Status.READY)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_sent(self, _mock):
        self.employee_record.prepare()
        filename = "RIAE_FS_20210410130000.json"
        self.employee_record.sent_in_asp_batch_file(filename)

        self.assertEquals(filename, self.employee_record.asp_batch_file)
        self.assertEquals(self.employee_record.status, EmployeeRecord.Status.SENT)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_rejected(self, _mock):
        self.employee_record.prepare()
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.sent_in_asp_batch_file(filename)

        err_code, err_message = "12", "JSON Invalide"

        self.employee_record.rejected_by_asp(err_code, err_message)
        self.assertEquals(self.employee_record.status, EmployeeRecord.Status.REJECTED)
        self.assertEquals(self.employee_record.asp_processing_code, err_code)
        self.assertEquals(self.employee_record.asp_processing_label, err_message)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def _test_state_accepted(self, _mock):
        self.employee_record.prepare()
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.sent_in_asp_batch_file(filename)

        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.accepted_by_asp(process_code, process_message)

        self.assertEquals(self.employee_record.status, EmployeeRecord.Status.PROCESSED)
        self.assertEquals(self.employee_record.asp_processing_code, process_code)
        self.assertEquals(self.employee_record.asp_processing_label, process_message)


@mock.patch("pysftp.Connection", SFTPConnectionMock)
class EmployeeRecordManagementCommandTest(TestCase):
    """
    Employee record management command, testing:
    - mocked sftp connection
    - basic upload / download modes
    - ...
    """

    fixtures = ["test_INSEE_communes.json", "asp_countries.json"]

    def test_smoke_download(self):
        command = Command()
        command.handle(download=True)

    def test_smoke_upload(self):
        command = Command()
        command.handle(upload=True)

    def test_smoke_download_and_upload(self):
        command = Command()
        command.handle()

    @mock.patch("pysftp.Connection", SFTPGoodConnectionMock)
    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_upload_and_download(self, _mock):
        """
        - Create an employee record
        - Send it to ASP
        - Get feedback
        - Update employee record
        """
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        employee_record.prepare()

        command = Command()
        command.handle(upload=True)

        employee_record.refresh_from_db()
        self.assertEquals(employee_record.status, EmployeeRecord.Status.SENT)

        # TODO
        # command = Command()
        # command.handle(download=True)

        # employee_record.refresh_from_db()
