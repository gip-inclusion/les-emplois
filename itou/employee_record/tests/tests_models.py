from datetime import date, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.employee_record import constants
from itou.employee_record.enums import Status
from itou.employee_record.exceptions import CloningError, InvalidStatusError
from itou.employee_record.factories import EmployeeRecordFactory, EmployeeRecordWithProfileFactory
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, validate_asp_batch_filename
from itou.employee_record.tests.common import EmployeeRecordFixtureTest
from itou.job_applications.factories import (
    JobApplicationWithApprovalFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
    JobApplicationWithJobSeekerProfileFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.apis.exceptions import AddressLookupError
from itou.utils.mocks.address_format import mock_get_geocoding_data


class EmployeeRecordModelTest(EmployeeRecordFixtureTest):
    def setUp(self):
        self.employee_record = EmployeeRecordFactory()

    # Validation tests

    def test_creation_with_jobseeker_without_title(self):
        with self.assertRaises(ValidationError):
            # If the job seeker has no title (optional by default),
            # Then the job seeker profile must not be valid
            job_application = JobApplicationWithJobSeekerProfileFactory()
            job_application.job_seeker.title = None
            EmployeeRecord.from_job_application(job_application)

    def test_creation_with_empty_value(self):
        with self.assertRaises(AssertionError):
            EmployeeRecord.from_job_application(None)

    def test_creation_with_bad_job_application_status(self):
        for state in [
            state.name
            for state in list(JobApplicationWorkflow.states)
            if state.name != JobApplicationWorkflow.STATE_ACCEPTED
        ]:
            with self.subTest(state):
                with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED):
                    job_application = JobApplicationWithApprovalFactory(state=state)
                    EmployeeRecord.from_job_application(job_application)

    def test_creation_without_approval(self):
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_WITHOUT_APPROVAL):
            job_application = JobApplicationWithoutApprovalFactory()
            EmployeeRecord.from_job_application(job_application)

    def test_creation_with_same_job_application(self):
        # Job application is duplicated (already existing with same approval and SIAE)
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()

        # Must be ok
        EmployeeRecord.from_job_application(job_application).save()

        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE):
            # Must not
            EmployeeRecord.from_job_application(job_application)

    def test_creation_without_jobseeker_profile(self):
        # Job seeker has no existing profile (must be filled before creation)
        with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_SEEKER_HAS_NO_PROFILE):
            job_application = JobApplicationWithApprovalNotCancellableFactory()
            EmployeeRecord.from_job_application(job_application)

    def test_creation_from_job_application(self):
        """
        Employee record objects are created from a job application giving them access to:
        - user / job seeker
        - job seeker profile
        - approval

        Creation is defensive, expect ValidationError if out of the way
        """

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
        job_application = JobApplicationWithJobSeekerProfileFactory()

        with self.assertRaises(AddressLookupError):
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
            status=Status.PROCESSED,
            processed_at=timezone.now(),
        )

        # Processed to recently, should not be found
        self.assertEqual(EmployeeRecord.objects.archivable().count(), 0)

        # Fake older date
        employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=constants.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )

        employee_record.save()

        self.assertEqual(EmployeeRecord.objects.archivable().count(), 1)

    def test_clone_orphan(self):
        # Check employee record clone features and properties
        good_employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        bad_employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        previous_asp_id = good_employee_record.asp_id

        good_employee_record.asp_id += 1
        good_employee_record.save()

        self.assertTrue(good_employee_record.is_orphan)

        clone = good_employee_record.clone_orphan(previous_asp_id)
        self.assertTrue(clone.pk != good_employee_record.pk)
        self.assertNotEqual(good_employee_record.created_at, clone.created_at)
        self.assertEqual(Status.READY, clone.status)
        self.assertEqual(previous_asp_id, clone.asp_id)
        self.assertIsNone(clone.asp_batch_file)
        self.assertIsNone(clone.asp_batch_line_number)
        self.assertIsNone(clone.asp_processing_code)
        self.assertIn(EmployeeRecord.ASP_CLONE_MESSAGE, clone.asp_processing_label)
        self.assertEqual(Status.DISABLED, good_employee_record.status)
        self.assertIsNone(clone.archived_json)

        # Check conditions are required

        with self.assertRaises(CloningError):
            # Clone with previous asp_id
            bad_employee_record.clone_orphan(previous_asp_id)

        with self.assertRaises(CloningError):
            # Not an orphan
            bad_employee_record.clone_orphan(bad_employee_record.asp_id)

        with self.assertRaises(CloningError):
            # Not saved (no PK)
            bad_employee_record.pk = None
            bad_employee_record.clone_orphan(-1)

        bad_employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        bad_employee_record.approval_number = good_employee_record.approval_number
        bad_employee_record.save()
        bad_employee_record.asp_id = -2

        with self.assertRaises(CloningError):
            # Other case: duplicate in db (pair approval_number,asp_id)
            bad_employee_record.clone_orphan(-1)


class EmployeeRecordBatchTest(EmployeeRecordFixtureTest):
    """
    Misc tests on batch wrapper level
    """

    def test_format_feedback_filename(self):
        with self.assertRaises(ValidationError):
            EmployeeRecordBatch.feedback_filename("test.json")

        self.assertEqual(
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


class EmployeeRecordLifeCycleTest(EmployeeRecordFixtureTest):
    """
    Note: employee records status is never changed manually
    """

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
        self.assertEqual(self.employee_record.status, Status.READY)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_sent(self, _mock):
        filename = "RIAE_FS_20210410130000.json"
        self.employee_record.update_as_sent(filename, 1)

        self.assertEqual(filename, self.employee_record.asp_batch_file)
        self.assertEqual(self.employee_record.status, Status.SENT)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_rejected(self, _mock):
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)

        err_code, err_message = "12", "JSON Invalide"

        self.employee_record.update_as_rejected(err_code, err_message)
        self.assertEqual(self.employee_record.status, Status.REJECTED)
        self.assertEqual(self.employee_record.asp_processing_code, err_code)
        self.assertEqual(self.employee_record.asp_processing_label, err_message)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_processed(self, _mock):
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "{}")

        self.assertEqual(self.employee_record.status, Status.PROCESSED)
        self.assertEqual(self.employee_record.asp_processing_code, process_code)
        self.assertEqual(self.employee_record.asp_processing_label, process_message)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_disabled(self, _mock):
        filename = "RIAE_FS_20210410130001.json"

        self.assertNotIn(
            self.employee_record.job_application,
            JobApplication.objects.eligible_as_employee_record(self.employee_record.job_application.to_siae),
        )

        # Employee record in READY state can't be disabled
        with self.assertRaisesMessage(InvalidStatusError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE):
            self.employee_record.update_as_disabled()
        self.assertEqual(self.employee_record.status, Status.READY)

        # Employee record in SENT state can't be disabled
        self.employee_record.update_as_sent(filename, 1)
        with self.assertRaisesMessage(InvalidStatusError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE):
            self.employee_record.update_as_disabled()
        self.assertEqual(self.employee_record.status, Status.SENT)

        # Employee record in ACCEPTED state can be disabled
        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "{}")
        self.employee_record.update_as_disabled()
        self.assertEqual(self.employee_record.status, Status.DISABLED)

        # Now, can create new employee record on same job_application
        new_employee_record = EmployeeRecord.from_job_application(self.employee_record.job_application)
        self.assertEqual(new_employee_record.status, Status.NEW)

        # Employee record in NEW state can be disable
        new_employee_record.update_as_disabled()
        self.assertEqual(new_employee_record.status, Status.DISABLED)

        # Now, can create another one employee record on same job_application
        new_employee_record = EmployeeRecord.from_job_application(new_employee_record.job_application)
        self.assertEqual(new_employee_record.status, Status.NEW)

        new_employee_record.update_as_ready()
        self.assertEqual(new_employee_record.status, Status.READY)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_disabled_with_reject(self, _mock):
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)

        self.assertNotIn(
            self.employee_record.job_application,
            JobApplication.objects.eligible_as_employee_record(self.employee_record.job_application.to_siae),
        )

        err_code, err_message = "12", "JSON Invalide"
        self.employee_record.update_as_rejected(err_code, err_message)
        self.employee_record.update_as_disabled()
        self.assertEqual(self.employee_record.status, Status.DISABLED)

        # Now, can create new employee record on same job_application
        new_employee_record = EmployeeRecord.from_job_application(self.employee_record.job_application)
        self.assertEqual(new_employee_record.status, Status.NEW)
        new_employee_record.update_as_ready()
        self.assertEqual(new_employee_record.status, Status.READY)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_reactivate(self, _mock):

        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)
        process_code = EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE
        process_message = "La ligne de la fiche salarié a été enregistrée avec succès."
        archive_first = '{"libelleTraitement":"La ligne de la fiche salarié a été enregistrée avec succès [1]."}'
        self.employee_record.update_as_processed(process_code, process_message, archive_first)
        self.employee_record.update_as_disabled()
        self.assertEqual(self.employee_record.status, Status.DISABLED)

        # Employee record in DISABLE state can be reactivate (set state NEW)
        self.employee_record.update_as_new()
        self.assertEqual(self.employee_record.status, Status.NEW)

        # Employee record can now be changed to the ready state
        self.employee_record.update_as_ready()
        self.assertEqual(self.employee_record.status, Status.READY)

        filename_second = "RIAE_FS_20210410130002.json"
        self.employee_record.update_as_sent(filename_second, 1)
        self.assertEqual(self.employee_record.archived_json, archive_first)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        archive_second = '{"libelleTraitement":"La ligne de la fiche salarié a été enregistrée avec succès [2]."}'
        self.employee_record.update_as_processed(process_code, process_message, archive_second)
        self.assertEqual(self.employee_record.archived_json, archive_second)
        self.assertEqual(self.employee_record.asp_batch_file, filename_second)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_archived(self, _mock):
        filename = "RIAE_FS_20210816130001.json"
        self.employee_record.update_as_sent(filename, 1)

        # No processing date at the moment
        self.assertIsNone(self.employee_record.processed_at)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "{}")

        # Can't archive, too recent
        with self.assertRaises(InvalidStatusError):
            self.employee_record.update_as_archived()

        # Fake old date, but not to old
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=constants.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS - 1
        )

        with self.assertRaises(InvalidStatusError):
            self.employee_record.update_as_archived()

        # Fake a date older than archiving delay
        self.employee_record.processed_at = timezone.now() - timezone.timedelta(
            days=constants.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        )

        self.employee_record.update_as_archived()

        # Check correct status and empty archived JSON
        self.assertEqual(self.employee_record.status, Status.ARCHIVED)
        self.assertIsNone(self.employee_record.archived_json)

    def test_processed_as_duplicate(self):
        # Check correct status when "manually" forcing status of an employee record
        # with a 3436 error code.
        employee_record_code_3436 = EmployeeRecordWithProfileFactory(
            status=Status.REJECTED,
            asp_processing_code="3436",
            asp_processing_label="Meh",
        )
        employee_record_other_code = EmployeeRecordWithProfileFactory(
            status=Status.REJECTED,
            asp_processing_code="3437",
            asp_processing_label="Meh Meh",
        )
        employee_record_other_status = EmployeeRecordWithProfileFactory(
            status=Status.PROCESSED,
            asp_processing_code="3437",
            asp_processing_label="Meh Meh Meh",
        )
        employee_record_code_3436.update_as_processed_as_duplicate()
        self.assertTrue(employee_record_code_3436.processed_as_duplicate)
        self.assertEqual(Status.PROCESSED, employee_record_code_3436.status)
        self.assertEqual("Statut forcé suite à doublon ASP", employee_record_code_3436.asp_processing_label)
        self.assertIsNone(employee_record_code_3436.archived_json)

        with self.assertRaises(InvalidStatusError):
            employee_record_other_code.update_as_processed_as_duplicate()

        with self.assertRaises(InvalidStatusError):
            employee_record_other_status.update_as_processed_as_duplicate()


class EmployeeRecordJobApplicationConstraintsTest(EmployeeRecordFixtureTest):
    """
    Check constraints between job applications and employee records
    """

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
        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "{}")
        self.assertFalse(self.job_application.can_be_cancelled)


class EmployeeRecordQuerysetTest(EmployeeRecordFixtureTest):
    def test_orphans(self):
        # Check orphans employee records
        # (asp_id in object different from actual SIAE convention asp_id field)
        orphan_employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)

        # Not an orphan, yet
        self.assertFalse(orphan_employee_record.is_orphan)
        self.assertEqual(0, EmployeeRecord.objects.orphans().count())

        # Whatever int different from asp_id will do, but factory sets this field at 0
        orphan_employee_record.asp_id += 1
        orphan_employee_record.save()

        self.assertTrue(orphan_employee_record.is_orphan)
        self.assertEqual(1, EmployeeRecord.objects.orphans().count())

    def test_asp_duplicates(self):
        # Filter REJECTED employee records with error code 3436
        EmployeeRecordWithProfileFactory(status=Status.REJECTED)

        self.assertEqual(0, EmployeeRecord.objects.asp_duplicates().count())

        EmployeeRecordWithProfileFactory(
            status=Status.REJECTED, asp_processing_code=EmployeeRecord.ASP_DUPLICATE_ERROR_CODE
        )

        self.assertEqual(1, EmployeeRecord.objects.asp_duplicates().count())
