from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.models import EmployeeRecord
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
            employee_record = EmployeeRecord.from_job_application(
                JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW)
            )

        # Job application can be cancelled
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_TOO_RECENT):
            employee_record = EmployeeRecord.from_job_application(
                JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
            )

        # Job application has no approval
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_WITHOUT_APPROVAL):
            employee_record = EmployeeRecord.from_job_application(JobApplicationWithoutApprovalFactory())

        # Job application is duplicated (already existing with same approval and SIAE)
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE):
            job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
            # Must be ok
            EmployeeRecord.from_job_application(job_application).save()
            # Must not
            employee_record = EmployeeRecord.from_job_application(job_application)

        # Job seeker has no existing profile (must be filled before creation)
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_SEEKER_HAS_NO_PROFILE):
            employee_record = EmployeeRecord.from_job_application(JobApplicationWithApprovalNotCancellableFactory())

        # Job seeker has an incomplete profile
        with self.assertRaises(ValidationError):
            # Message checked in profile tests
            employee_record = EmployeeRecord.from_job_application(JobApplicationWithJobSeekerProfileFactory())

        # Standard / normal case
        employee_record = EmployeeRecord.from_job_application(JobApplicationWithCompleteJobSeekerProfileFactory())
        self.assertIsNotNone(employee_record)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_prepare_successful(self, _):
        """
        Mainly format the job seeker address to Hexa format
        """
        employee_record = EmployeeRecord.from_job_application(JobApplicationWithCompleteJobSeekerProfileFactory())
        self.assertEquals(employee_record.status, EmployeeRecord.Status.NEW)

        employee_record.prepare()
        self.assertEquals(employee_record.status, EmployeeRecord.Status.READY)

    def test_prepare_failed(self):
        """
        Test the failure of employee record preparation
        """


class EmployeeRecordLifeCycleTest(TestCase):
    pass
