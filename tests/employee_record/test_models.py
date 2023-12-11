import datetime
import itertools
import json
from datetime import date, timedelta
from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.approvals.models import Approval
from itou.employee_record.enums import Status
from itou.employee_record.exceptions import InvalidStatusError
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, validate_asp_batch_filename
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.mocks.address_format import mock_get_geocoding_data
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import (
    BareEmployeeRecordFactory,
    BareEmployeeRecordUpdateNotificationFactory,
    EmployeeRecordFactory,
    EmployeeRecordWithProfileFactory,
)
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
    JobApplicationWithoutApprovalFactory,
)
from tests.utils.test import TestCase


@pytest.mark.usefixtures("unittest_compatibility")
class EmployeeRecordModelTest(TestCase):
    def setUp(self):
        super().setUp()
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

        old_siae, old_approval = job_application.to_company, job_application.approval
        new_company, new_approval = CompanyFactory(), ApprovalFactory()

        employee_record.job_application.to_company = new_company
        employee_record.job_application.approval = new_approval
        employee_record.job_application.save()

        assert employee_record.siret == old_siae.siret
        assert employee_record.asp_id == old_siae.convention.asp_id
        assert employee_record.approval_number == old_approval.number

        employee_record.update_as_ready()

        employee_record.refresh_from_db()
        assert employee_record.siret == new_company.siret
        assert employee_record.asp_id == new_company.convention.asp_id
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
        six_months_ago = timezone.now() - relativedelta(months=6)
        one_month_ago = timezone.now() - relativedelta(months=1)
        parameters = itertools.product(
            [True, False],
            [
                self.faker.date_time_between(end_date=six_months_ago, tzinfo=datetime.UTC),
                self.faker.date_time_between(start_date=six_months_ago, tzinfo=datetime.UTC),
            ],
            [
                self.faker.date_time_between(end_date=one_month_ago, tzinfo=datetime.UTC),
                self.faker.date_time_between(start_date=one_month_ago, tzinfo=datetime.UTC),
            ],
        )
        for expired, created_at, updated_at in parameters:
            EmployeeRecordFactory(
                job_application__approval__expired=expired,
                created_at=created_at,
                updated_at=updated_at,
            )

        assert EmployeeRecord.objects.archivable().count() == 1

    def test_archivable_with_archived_employee_record(self):
        EmployeeRecordFactory(
            status=Status.ARCHIVED,
            archivable=True,
        )
        assert EmployeeRecord.objects.archivable().count() == 0


@pytest.mark.parametrize(
    "factory,expected",
    [
        (JobApplicationSentByJobSeekerFactory, "07"),
        (JobApplicationSentByCompanyFactory, "07"),
        (JobApplicationSentByPrescriberFactory, "08"),
        (JobApplicationSentByPrescriberOrganizationFactory, "08"),
    ],
)
def test_asp_prescriber_type_for_other_sender(factory, expected):
    employee_record = EmployeeRecordFactory(
        job_application=factory(with_approval=True),
    )
    assert employee_record.asp_prescriber_type == expected


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("CAP_EMPLOI", "02"),
        ("ML", "01"),
        ("OIL", "06"),
        ("ODC", "06"),
        ("PENSION", "06"),
        ("PE", "03"),
        ("RS_FJT", "06"),
        ("PREVENTION", "14"),
        ("DEPT", "05"),
        ("AFPA", "15"),
        ("ASE", "19"),
        ("CAARUD", "06"),
        ("CADA", "18"),
        ("CAF", "17"),
        ("CAVA", "20"),
        ("CCAS", "11"),
        ("CHRS", "12"),
        ("CHU", "22"),
        ("CIDFF", "13"),
        ("CPH", "21"),
        ("CSAPA", "06"),
        ("E2C", "06"),
        ("EPIDE", "06"),
        ("HUDA", "06"),
        ("MSA", "06"),
        ("OACAS", "23"),
        ("PIJ_BIJ", "16"),
        ("PJJ", "10"),
        ("PLIE", "04"),
        ("SPIP", "09"),
        ("OTHER", "06"),
    ],
)
def test_asp_prescriber_type_for_authorized_organization(kind, expected):
    employee_record = EmployeeRecordFactory(
        job_application__sent_by_authorized_prescriber_organisation=True,
        job_application__sender_prescriber_organization__kind=kind,
    )
    assert employee_record.asp_prescriber_type == expected


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
        super().setUp()
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
            self.employee_record.job_application.to_company
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

        # Employee record in DISABLED state block creating a new one
        with pytest.raises(ValidationError):
            EmployeeRecord.from_job_application(self.employee_record.job_application)

        # Employee record in NEW state can be disabled
        self.employee_record.update_as_new()
        assert self.employee_record.status == Status.NEW
        self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.DISABLED

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_state_disabled_with_reject(self, _mock):
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        assert self.employee_record.job_application not in JobApplication.objects.eligible_as_employee_record(
            self.employee_record.job_application.to_company
        )

        self.employee_record.update_as_rejected("12", "JSON Invalide", None)
        self.employee_record.update_as_disabled()
        assert self.employee_record.status == Status.DISABLED

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
        new_company = CompanyFactory(use_employee_record=True)
        old_company = self.employee_record.job_application.to_company

        assert self.employee_record.siret == old_company.siret
        assert self.employee_record.asp_id == old_company.asp_id

        self.employee_record.update_as_sent(self.faker.unique.asp_batch_filename(), 1, None)
        self.employee_record.update_as_processed("", "", None)
        self.employee_record.update_as_disabled()

        # Change SIAE
        self.employee_record.job_application.to_company = new_company
        self.employee_record.job_application.save()
        self.employee_record.refresh_from_db()
        # Reactivate the employee record
        self.employee_record.update_as_new()

        assert self.employee_record.siret == new_company.siret
        assert self.employee_record.asp_id == new_company.asp_id

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
        approval.start_at = timezone.localdate() - relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval.end_at = timezone.localdate() - relativedelta(months=1)
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
        super().setUp()
        # Make job application cancellable
        hiring_date = date.today() + timedelta(days=7)

        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(hiring_start_at=hiring_date)
        self.employee_record = EmployeeRecord.from_job_application(self.job_application)
        self.employee_record.update_as_ready()


class TestEmployeeRecordQueryset:
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

        assert (
            EmployeeRecord.objects.for_company(employee_record_1.job_application.to_company).get() == employee_record_1
        )
        assert (
            EmployeeRecord.objects.for_company(employee_record_2.job_application.to_company).get() == employee_record_2
        )

    def test_for_siae_with_different_asp_id(self):
        employee_record = EmployeeRecordFactory(asp_id=0)

        assert list(EmployeeRecord.objects.for_company(employee_record.job_application.to_company)) == [
            employee_record
        ]


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
