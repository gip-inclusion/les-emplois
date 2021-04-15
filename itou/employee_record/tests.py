from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.models import EmployeeRecord, validate_asp_batch_filename
from itou.job_applications.factories import (
    JobApplicationFactory,
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


class EmployeeRecordLifeCycleTest(TestCase):
    """
    Employee record status is never changed manually
    """

    fixtures = ["test_INSEE_communes.json"]

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_ready(self, _mock):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)

        self.assertEquals(employee_record.status, EmployeeRecord.Status.NEW)

        employee_record.prepare()

        self.assertEquals(employee_record.status, EmployeeRecord.Status.READY)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_sent(self, _mock):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)

        employee_record.prepare()
        employee_record.sent_in_asp_batch_file("RIAE_FS_20210410130000.json")
