import json
from datetime import date, timedelta
from unittest import mock

import freezegun
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.approvals.factories import ApprovalFactory
from itou.employee_record.enums import Status
from itou.employee_record.exceptions import CloningError, DuplicateCloningError, InvalidStatusError
from itou.employee_record.factories import (
    BareEmployeeRecordFactory,
    BareEmployeeRecordUpdateNotificationFactory,
    EmployeeRecordFactory,
    EmployeeRecordWithProfileFactory,
)
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, validate_asp_batch_filename
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.factories import SiaeFactory
from itou.utils.mocks.address_format import mock_get_geocoding_data
from itou.utils.test import TestCase


@pytest.mark.usefixtures("unittest_compatibility")
class EmployeeRecordModelTest(TestCase):
    def setUp(self):
        self.employee_record = EmployeeRecordFactory()

    # Validation tests

    def test_creation_with_jobseeker_without_title(self):
        with pytest.raises(ValidationError):
            # If the job seeker has no title (optional by default),
            # Then the job seeker profile must not be valid
            job_application = JobApplicationWithApprovalNotCancellableFactory()
            job_application.job_seeker.title = None
            EmployeeRecord.from_job_application(job_application)

    def test_creation_with_empty_value(self):
        with pytest.raises(AssertionError):
            EmployeeRecord.from_job_application(None)

    def test_creation_with_bad_job_application_status(self):
        for state in [
            state.name
            for state in list(JobApplicationWorkflow.states)
            if state.name != JobApplicationWorkflow.STATE_ACCEPTED
        ]:
            with self.subTest(state):
                with self.assertRaisesMessage(ValidationError, EmployeeRecord.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED):
                    job_application = JobApplicationFactory(with_approval=True, state=state)
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
        assert employee_record is not None

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
        assert job_seeker.jobseeker_profile is not None

        # Surface check, this is not a job seeker profile test
        profile = job_seeker.jobseeker_profile
        assert profile.hexa_commune is not None

    def test_prepare_failed_geoloc(self):
        """
        Test the failure of employee record preparation

        Mainly caused by:
        - geoloc issues (no API mock on this test)
        """
        # Complete profile, but geoloc API not reachable
        job_application = JobApplicationWithApprovalNotCancellableFactory()

        with pytest.raises(ValidationError):
            employee_record = EmployeeRecord.from_job_application(job_application)
            employee_record.update_as_ready()

    def test_update_as_ready_fill_denormalized_fields(self):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)

        old_siae, old_approval = job_application.to_siae, job_application.approval
        new_siae, new_approval = SiaeFactory(), ApprovalFactory()

        employee_record.job_application.to_siae = new_siae
        employee_record.job_application.approval = new_approval
        employee_record.job_application.save()

        assert employee_record.siret == old_siae.siret
        assert employee_record.asp_id == old_siae.convention.asp_id
        assert employee_record.approval_number == old_approval.number

        employee_record.update_as_ready()

        employee_record.refresh_from_db()
        assert employee_record.siret == new_siae.siret
        assert employee_record.asp_id == new_siae.convention.asp_id
        assert employee_record.approval_number == new_approval.number

    def test_batch_filename_validator(self):
        """
        Check format of ASP batch file name
        """
        with pytest.raises(ValidationError):
            validate_asp_batch_filename(None)

        with pytest.raises(ValidationError):
            validate_asp_batch_filename("xyz")

        with pytest.raises(ValidationError):
            validate_asp_batch_filename("RiAE_20210410130000.json")

        validate_asp_batch_filename("RIAE_FS_20210410130000.json")

    def test_find_by_batch(self):
        """
        How to find employee records given their ASP batch file name and line number ?
        """
        employee_record = EmployeeRecordFactory(with_batch_information=True)

        assert EmployeeRecord.objects.find_by_batch("X", employee_record.asp_batch_line_number).count() == 0
        assert EmployeeRecord.objects.find_by_batch(employee_record.asp_batch_file, 0).count() == 0

        result = EmployeeRecord.objects.find_by_batch(
            employee_record.asp_batch_file, employee_record.asp_batch_line_number
        ).first()

        assert result.id == employee_record.id

    def test_archivable(self):
        EmployeeRecordFactory()
        assert EmployeeRecord.objects.archivable().count() == 0

        archivable_employee_record = EmployeeRecordFactory(job_application__approval__expired=True)
        assert list(EmployeeRecord.objects.archivable()) == [archivable_employee_record]


@pytest.mark.parametrize("status", list(Status))
def test_clone_for_orphan_employee_record(status):
    # Check employee record clone features and properties
    employee_record = EmployeeRecordFactory(orphan=True, status=status)

    assert employee_record.is_orphan
    with freezegun.freeze_time():
        clone = employee_record.clone()
    assert not clone.is_orphan

    # Check fields that changes during cloning
    assert clone.pk != employee_record.pk
    assert clone.status == Status.NEW
    assert clone.asp_processing_label == f"Fiche salarié clonée (pk origine: {employee_record.pk})"
    assert clone.created_at != employee_record.created_at
    assert clone.updated_at == clone.created_at

    # Check fields that are copied or possibly overwritten
    assert clone.job_application == employee_record.job_application
    assert clone.approval_number == employee_record.approval_number
    assert clone.asp_id == employee_record.job_application.to_siae.convention.asp_id
    assert clone.siret == employee_record.job_application.to_siae.siret

    # Check fields that should be empty
    assert clone.asp_processing_code is None
    assert clone.asp_batch_file is None
    assert clone.asp_batch_line_number is None
    assert clone.archived_json is None
    assert clone.processed_at is None
    assert clone.financial_annex is None
    assert clone.processed_as_duplicate is False

    # Check cloned employee record
    assert employee_record.is_orphan
    if employee_record.can_be_disabled:
        assert employee_record.status == Status.DISABLED


def test_clone_for_disabled_employee_record():
    employee_record = EmployeeRecordFactory(status=Status.DISABLED)

    clone = employee_record.clone()
    assert clone.pk != employee_record.pk
    # Cloned employee record should be DISABLED
    assert employee_record.status == Status.DISABLED


def test_clone_when_a_duplicate_exists():
    employee_record = EmployeeRecordFactory()
    with pytest.raises(DuplicateCloningError, match=r"The clone is a duplicate of"):
        employee_record.clone()


def test_clone_without_primary_key():
    employee_record = BareEmployeeRecordFactory.build()
    with pytest.raises(CloningError) as exc_info:
        employee_record.clone()
    assert str(exc_info.value) == "This employee record has not been saved yet (no PK)."


def test_clone_without_convention():
    employee_record = EmployeeRecordFactory(orphan=True, job_application__to_siae__convention=None)
    with pytest.raises(CloningError, match=r"SIAE \d{14} has no convention"):
        employee_record.clone()


class EmployeeRecordBatchTest(TestCase):
    """
    Misc tests on batch wrapper level
    """

    def test_format_feedback_filename(self):
        with pytest.raises(ValidationError):
            EmployeeRecordBatch.feedback_filename("test.json")

        assert "RIAE_FS_20210410130000_FichierRetour.json" == EmployeeRecordBatch.feedback_filename(
            "RIAE_FS_20210410130000.json"
        )

    def test_batch_filename_from_feedback(self):
        with pytest.raises(ValidationError):
            EmployeeRecordBatch.batch_filename_from_feedback("test.json")

        assert "RIAE_FS_20210410130000.json" == EmployeeRecordBatch.batch_filename_from_feedback(
            "RIAE_FS_20210410130000_FichierRetour.json"
        )


@pytest.mark.usefixtures("unittest_compatibility")
class EmployeeRecordLifeCycleTest(TestCase):
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
        assert self.employee_record.status == Status.READY

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_sent(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 42, "{}")

        assert self.employee_record.status == Status.SENT
        assert self.employee_record.asp_batch_line_number == 42
        assert self.employee_record.archived_json == {}

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_rejected(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        self.employee_record.update_as_rejected("12", "JSON Invalide", "{}")
        assert self.employee_record.status == Status.REJECTED
        assert self.employee_record.asp_processing_code == "12"
        assert self.employee_record.asp_processing_label == "JSON Invalide"
        assert self.employee_record.archived_json == {}

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_processed(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "{}")

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json == {}

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_processed_when_archive_is_none(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, None)

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json is None

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_processed_when_archive_is_empty(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "")

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json == ""

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_processed_when_archive_is_not_json(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "whatever")

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json == "whatever"

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_disabled(self, _mock):
        assert self.employee_record.job_application not in JobApplication.objects.eligible_as_employee_record(
            self.employee_record.job_application.to_siae
        )

        # Employee record in READY state can't be disabled
        with self.assertRaisesMessage(InvalidStatusError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE):
            self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.READY

        # Employee record in SENT state can't be disabled
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)
        with self.assertRaisesMessage(InvalidStatusError, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE):
            self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.SENT

        # Employee record in ACCEPTED state can be disabled
        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.update_as_processed(process_code, process_message, "{}")
        self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.DISABLED

        # Now, can create new employee record on same job_application
        new_employee_record = EmployeeRecord.from_job_application(self.employee_record.job_application)
        assert new_employee_record.status == Status.NEW

        # Employee record in NEW state can be disable
        new_employee_record.update_as_disabled()
        assert new_employee_record.status == Status.DISABLED

        # Now, can create another one employee record on same job_application
        new_employee_record = EmployeeRecord.from_job_application(new_employee_record.job_application)
        assert new_employee_record.status == Status.NEW

        new_employee_record.update_as_ready()
        assert new_employee_record.status == Status.READY

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_disabled_with_reject(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        assert self.employee_record.job_application not in JobApplication.objects.eligible_as_employee_record(
            self.employee_record.job_application.to_siae
        )

        self.employee_record.update_as_rejected("12", "JSON Invalide", None)
        self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.DISABLED

        # Now, can create new employee record on same job_application
        new_employee_record = EmployeeRecord.from_job_application(self.employee_record.job_application)
        assert new_employee_record.status == Status.NEW
        new_employee_record.update_as_ready()
        assert new_employee_record.status == Status.READY

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_reactivate(self, _mock):
        self.employee_record.update_as_sent(self.faker.unique.asp_batch_filename(), 1, None)
        process_code = EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE
        process_message = "La ligne de la fiche salarié a été enregistrée avec succès."
        archive_first = '{"libelleTraitement":"La ligne de la fiche salarié a été enregistrée avec succès [1]."}'
        self.employee_record.update_as_processed(process_code, process_message, archive_first)
        self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.DISABLED

        # Employee record in DISABLE state can be reactivate (set state NEW)
        self.employee_record.update_as_new()
        assert self.employee_record.status == Status.NEW

        # Employee record can now be changed to the ready state
        self.employee_record.update_as_ready()
        assert self.employee_record.status == Status.READY

        filename_second = self.faker.unique.asp_batch_filename()
        archive_second = '{"libelleTraitement":"La ligne de la fiche salarié a été enregistrée avec succès [2]."}'
        self.employee_record.update_as_sent(filename_second, 1, archive_second)
        assert self.employee_record.asp_batch_file == filename_second
        assert self.employee_record.archived_json == json.loads(archive_second)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        archive_third = '{"libelleTraitement":"La ligne de la fiche salarié a été enregistrée avec succès [3]."}'
        self.employee_record.update_as_processed(process_code, process_message, archive_third)
        assert self.employee_record.asp_batch_file == filename_second
        assert self.employee_record.archived_json == json.loads(archive_third)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_reactivate_when_the_siae_has_changed(self, _mock):
        new_siae = SiaeFactory(use_employee_record=True)
        old_siae = self.employee_record.job_application.to_siae

        assert self.employee_record.siret == old_siae.siret
        assert self.employee_record.asp_id == old_siae.asp_id

        self.employee_record.update_as_sent(self.faker.unique.asp_batch_filename(), 1, None)
        self.employee_record.update_as_processed("", "", None)
        self.employee_record.update_as_disabled()

        # Change SIAE
        self.employee_record.job_application.to_siae = new_siae
        self.employee_record.job_application.save()
        self.employee_record.refresh_from_db()
        # Reactivate the employee record
        self.employee_record.update_as_new()

        assert self.employee_record.siret == new_siae.siret
        assert self.employee_record.asp_id == new_siae.asp_id

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_archived(self, _mock):
        approval = self.employee_record.job_application.approval

        # Can't archive while the approval is valid
        assert approval.is_valid()
        with pytest.raises(InvalidStatusError):
            self.employee_record.update_as_archived()

        # Make the approval expires
        approval.start_at = timezone.now().date() - timedelta(days=2)
        approval.end_at = timezone.now().date() - timedelta(days=1)
        approval.save()
        assert not approval.is_valid()

        self.employee_record.update_as_archived()
        # Check correct status and empty archived JSON
        assert self.employee_record.status == Status.ARCHIVED
        assert self.employee_record.archived_json is None

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
        employee_record_code_3436.update_as_processed_as_duplicate('{"codeTraitement": "3436"}')
        assert employee_record_code_3436.processed_as_duplicate
        assert Status.PROCESSED == employee_record_code_3436.status
        assert "Statut forcé suite à doublon ASP" == employee_record_code_3436.asp_processing_label
        assert employee_record_code_3436.archived_json == {"codeTraitement": "3436"}

        with pytest.raises(InvalidStatusError):
            employee_record_other_code.update_as_processed_as_duplicate(None)

        with pytest.raises(InvalidStatusError):
            employee_record_other_status.update_as_processed_as_duplicate(None)


@pytest.mark.usefixtures("unittest_compatibility")
class EmployeeRecordJobApplicationConstraintsTest(TestCase):
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


class TestEmployeeRecordQueryset:
    @pytest.mark.parametrize("status", list(Status))
    def test_orphans(self, status):
        # Check orphans employee records
        # (asp_id in object different from actual SIAE convention asp_id field)
        employee_record = EmployeeRecordFactory(status=status)

        # Not an orphan, yet
        assert employee_record.is_orphan is False
        assert EmployeeRecord.objects.orphans().count() == 0

        # Whatever int different from asp_id will do, but factory sets this field at 0
        employee_record.asp_id += 1
        employee_record.save()

        assert employee_record.is_orphan is True
        assert EmployeeRecord.objects.orphans().count() == 1

    def test_asp_duplicates(self):
        # Filter REJECTED employee records with error code 3436
        EmployeeRecordWithProfileFactory(status=Status.REJECTED)

        assert EmployeeRecord.objects.asp_duplicates().count() == 0

        EmployeeRecordWithProfileFactory(
            status=Status.REJECTED, asp_processing_code=EmployeeRecord.ASP_DUPLICATE_ERROR_CODE
        )

        assert EmployeeRecord.objects.asp_duplicates().count() == 1

    def test_for_siae(self):
        employee_record_1, employee_record_2 = EmployeeRecordFactory.create_batch(2)

        assert EmployeeRecord.objects.for_siae(employee_record_1.job_application.to_siae).get() == employee_record_1
        assert EmployeeRecord.objects.for_siae(employee_record_2.job_application.to_siae).get() == employee_record_2

    def test_for_siae_with_different_asp_id(self):
        employee_record = EmployeeRecordFactory(
            asp_id=0,
        )

        assert list(EmployeeRecord.objects.for_siae(employee_record.job_application.to_siae)) == []


@pytest.mark.parametrize("factory", [BareEmployeeRecordFactory, BareEmployeeRecordUpdateNotificationFactory])
@pytest.mark.parametrize(
    "archive,expected_archive",
    [
        ('{"Hello": "World"}', {"Hello": "World"}),
        ("{}", {}),
        ("", ""),
        (None, None),
    ],
    ids=repr,
)
class TestASPExchangeInformationModel:
    def test_set_asp_batch_information(self, factory, archive, expected_archive):
        obj = factory()

        obj.set_asp_batch_information("RIAE_FS_20230123103950.json", 42, archive)
        obj.save()
        obj.refresh_from_db()

        assert obj.asp_batch_file == "RIAE_FS_20230123103950.json"
        assert obj.asp_batch_line_number == 42
        assert obj.archived_json == expected_archive

    @pytest.mark.parametrize(
        "code,expected_code",
        [
            ("0000", "0000"),
            (9999, "9999"),
        ],
        ids=repr,
    )
    def test_set_asp_processing_information(self, factory, archive, expected_archive, code, expected_code):
        obj = factory()

        obj.set_asp_processing_information(code, "The label", archive)
        obj.save()
        obj.refresh_from_db()

        assert obj.asp_processing_code == expected_code
        assert obj.asp_processing_label == "The label"
        assert obj.archived_json == expected_archive
