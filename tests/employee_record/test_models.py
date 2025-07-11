import datetime
import functools
import itertools
from datetime import timedelta
from unittest import mock

import pgtrigger
import pytest
import xworkflows
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.approvals.models import Approval
from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.employee_record.models import (
    EmployeeRecord,
    EmployeeRecordBatch,
    EmployeeRecordTransition,
    EmployeeRecordTransitionLog,
    EmployeeRecordWorkflow,
    validate_asp_batch_filename,
)
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationWorkflow
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
)
from tests.users.factories import EmployerFactory


class TestEmployeeRecordModel:
    def setup_method(self):
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

    def test_creation_with_bad_job_application_status(self, subtests):
        for state in [
            state.name for state in list(JobApplicationWorkflow.states) if state.name != JobApplicationState.ACCEPTED
        ]:
            with subtests.test(state):
                with pytest.raises(ValidationError) as exc:
                    job_application = JobApplicationFactory(with_approval=True, state=state)
                    EmployeeRecord.from_job_application(job_application)
                assert exc.value.message == EmployeeRecord.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED

    def test_creation_without_approval(self):
        with pytest.raises(ValidationError) as exc:
            job_application = JobApplicationFactory(state=JobApplicationState.ACCEPTED)
            EmployeeRecord.from_job_application(job_application)
        assert exc.value.message == EmployeeRecord.ERROR_JOB_APPLICATION_WITHOUT_APPROVAL

    def test_creation_with_same_job_application(self):
        # Job application is duplicated (already existing with same approval and SIAE)
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()

        # Must be ok
        EmployeeRecord.from_job_application(job_application).save()

        with pytest.raises(ValidationError) as exc:
            # Must not
            EmployeeRecord.from_job_application(job_application)
        assert exc.value.message == EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE

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
        employee_record.ready()

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
            employee_record.ready()

    def test_ready_fill_denormalized_fields(self):
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

        employee_record.ready()

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

    def test_archivable(self, faker):
        six_months_ago = timezone.now() - relativedelta(months=6)
        one_month_ago = timezone.now() - relativedelta(months=1)
        parameters = itertools.product(
            [True, False],
            [
                faker.date_time_between(end_date=six_months_ago, tzinfo=datetime.UTC),
                faker.date_time_between(start_date=six_months_ago, tzinfo=datetime.UTC),
            ],
            [
                faker.date_time_between(end_date=one_month_ago, tzinfo=datetime.UTC),
                faker.date_time_between(start_date=one_month_ago, tzinfo=datetime.UTC),
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

    def test_unarchive_with_wrong_status(self, subtests):
        for status in set(Status) - {Status.ARCHIVED}:
            with subtests.test(status=status.name):
                employee_record = BareEmployeeRecordFactory(status=status)
                with pytest.raises(xworkflows.InvalidTransitionError):
                    employee_record.unarchive()

    def test_unarchive(self, faker, subtests):
        specs = {
            None: Status.NEW,
            "0000": Status.PROCESSED,
            faker.numerify("31##"): Status.ARCHIVED,
            faker.numerify("32##"): Status.REJECTED,
            faker.numerify("33##"): Status.REJECTED,
            faker.numerify("340#"): Status.REJECTED,
            "3436": Status.PROCESSED,
            faker.numerify("35##"): Status.ARCHIVED,
        }

        for code, expected_status in specs.items():
            with subtests.test(code=code):
                employee_record = BareEmployeeRecordFactory(status=Status.ARCHIVED, asp_processing_code=code)
                employee_record.unarchive()
                assert employee_record.status == expected_status

    def test_unarchive_create_the_missed_notification(self, faker):
        employee_record_before_approval = EmployeeRecordFactory(
            status=Status.ARCHIVED,
            updated_at=faker.date_time_between(end_date="-1y", tzinfo=datetime.UTC),
            job_application__approval__updated_at=faker.date_time_between(
                start_date="-1y", end_date="-1d", tzinfo=datetime.UTC
            ),
        )
        employee_record_after_approval = EmployeeRecordFactory(
            status=Status.ARCHIVED,
            updated_at=faker.date_time_between(start_date="-1y", end_date="-1d", tzinfo=datetime.UTC),
            job_application__approval__updated_at=faker.date_time_between(end_date="-1y", tzinfo=datetime.UTC),
        )

        assert employee_record_before_approval.update_notifications.all().count() == 0
        employee_record_before_approval.unarchive()
        assert employee_record_before_approval.update_notifications.all().count() == 1

        assert employee_record_after_approval.update_notifications.all().count() == 0
        employee_record_after_approval.unarchive()
        assert employee_record_after_approval.update_notifications.all().count() == 0

    @pytest.mark.parametrize(
        "code,expected",
        [
            (None, Status.NEW),
            ("0000", Status.PROCESSED),
            ("31", None),
            ("32", Status.REJECTED),
            ("33", Status.REJECTED),
            ("34", Status.REJECTED),
            ("3436", Status.PROCESSED),
        ],
    )
    def test_status_based_on_asp_processing_code(self, code, expected):
        employee_record = BareEmployeeRecordFactory(asp_processing_code=code)
        assert employee_record.status_based_on_asp_processing_code is expected

    @pgtrigger.ignore("companies.Company:company_fields_history")
    def test_has_siret_different_form_asp_source(self):
        employee_record = EmployeeRecordFactory(
            job_application__to_company__siret="10000000000001", job_application__to_company__source=Company.SOURCE_ASP
        )
        employee_record._fill_denormalized_fields()  # to run siret_from_asp_source(main_company)
        company = employee_record.job_application.to_company

        assert employee_record.has_siret_different_from_asp_source() is False

        company.siret = "20000000000001"
        company.save()

        assert employee_record.has_siret_different_from_asp_source() is True

    @pgtrigger.ignore("companies.Company:company_fields_history")
    def test_has_siret_different_form_asp_source_for_antenna(self):
        main_company = CompanyFactory(source=Company.SOURCE_ASP, siret="10000000000001")
        employee_record = EmployeeRecordFactory(
            job_application__to_company__siret="10000000000002",
            job_application__to_company__source=Company.SOURCE_USER_CREATED,
            job_application__to_company__convention=main_company.convention,
        )
        employee_record._fill_denormalized_fields()  # to run siret_from_asp_source(main_company)

        assert employee_record.has_siret_different_from_asp_source() is False

        main_company.siret = "20000000000001"
        main_company.save()

        assert employee_record.has_siret_different_from_asp_source() is True


@pytest.mark.parametrize(
    "factory,expected",
    [
        pytest.param(
            functools.partial(JobApplicationSentByJobSeekerFactory, with_iae_eligibility_diagnosis=True),
            "07",
            id="JobApplicationSentByJobSeekerFactory-07",
        ),
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
        ("FT", "03"),
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


class TestEmployeeRecordBatch:
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


class TestEmployeeRecordLifeCycle:
    """
    Note: employee records status is never changed manually
    """

    @pytest.fixture(autouse=True)
    def setup_method(self, mocker):
        mocker.patch(
            "itou.common_apps.address.format.get_geocoding_data",
            side_effect=mock_get_geocoding_data,
        )
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        self.employee_record = employee_record
        self.employee_record.ready()

    def test_state_ready(
        self,
    ):
        assert self.employee_record.status == Status.READY

    def test_state_sent(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=42, archive={})

        assert self.employee_record.status == Status.SENT
        assert self.employee_record.asp_batch_line_number == 42
        assert self.employee_record.archived_json == {}

    def test_state_rejected(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        self.employee_record.reject(code="12", label="JSON Invalide", archive={})
        assert self.employee_record.status == Status.REJECTED
        assert self.employee_record.asp_processing_code == "12"
        assert self.employee_record.asp_processing_label == "JSON Invalide"
        assert self.employee_record.archived_json == {}

    def test_state_processed(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.process(code=process_code, label=process_message, archive={})

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json == {}

    def test_state_processed_when_archive_is_none(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.process(code=process_code, label=process_message, archive=None)

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json is None

    def test_state_processed_when_archive_is_empty(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.process(code=process_code, label=process_message, archive="")

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json == ""

    def test_state_processed_when_archive_is_not_json(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.process(code=process_code, label=process_message, archive="whatever")

        assert self.employee_record.status == Status.PROCESSED
        assert self.employee_record.asp_processing_code == process_code
        assert self.employee_record.asp_processing_label == process_message
        assert self.employee_record.archived_json == "whatever"

    def test_state_disabled(self, faker):
        # Employee record in READY state can't be disabled
        with pytest.raises(xworkflows.InvalidTransitionError):
            self.employee_record.disable()
        assert self.employee_record.status == Status.READY

        # Employee record in SENT state can't be disabled
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)
        with pytest.raises(xworkflows.InvalidTransitionError):
            self.employee_record.disable()
        assert self.employee_record.status == Status.SENT

        # Employee record in ACCEPTED state can be disabled
        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        self.employee_record.process(code=process_code, label=process_message, archive={})
        self.employee_record.disable()
        assert self.employee_record.status == Status.DISABLED

        # Employee record in DISABLED state block creating a new one
        with pytest.raises(ValidationError):
            EmployeeRecord.from_job_application(self.employee_record.job_application)

        # Employee record in NEW state can be disabled
        self.employee_record.enable()
        assert self.employee_record.status == Status.NEW
        self.employee_record.disable()
        assert self.employee_record.status == Status.DISABLED

    def test_state_disabled_with_reject(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        self.employee_record.reject(code="12", label="JSON Invalide", archive=None)
        self.employee_record.disable()
        assert self.employee_record.status == Status.DISABLED

    def test_reactivate(self, faker):
        self.employee_record.wait_for_asp_response(file=faker.unique.asp_batch_filename(), line_number=1, archive=None)
        process_code = EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE
        process_message = "La ligne de la fiche salarié a été enregistrée avec succès."
        archive_first = {"libelleTraitement": "La ligne de la fiche salarié a été enregistrée avec succès [1]."}
        self.employee_record.process(code=process_code, label=process_message, archive=archive_first)
        self.employee_record.disable()
        assert self.employee_record.status == Status.DISABLED

        # Employee record in DISABLE state can be reactivate (set state NEW)
        self.employee_record.enable()
        assert self.employee_record.status == Status.NEW

        # Employee record can now be changed to the ready state
        self.employee_record.ready()
        assert self.employee_record.status == Status.READY

        filename_second = faker.unique.asp_batch_filename()
        archive_second = {"libelleTraitement": "La ligne de la fiche salarié a été enregistrée avec succès [2]."}
        self.employee_record.wait_for_asp_response(file=filename_second, line_number=1, archive=archive_second)
        assert self.employee_record.asp_batch_file == filename_second
        assert self.employee_record.archived_json == archive_second

        process_code, process_message = (
            EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
            "La ligne de la fiche salarié a été enregistrée avec succès.",
        )
        archive_third = {"libelleTraitement": "La ligne de la fiche salarié a été enregistrée avec succès [3]."}
        self.employee_record.process(code=process_code, label=process_message, archive=archive_third)
        assert self.employee_record.asp_batch_file == filename_second
        assert self.employee_record.archived_json == archive_third

    def test_reactivate_when_the_siae_has_changed(self, faker):
        new_company = CompanyFactory(use_employee_record=True)
        old_company = self.employee_record.job_application.to_company

        assert self.employee_record.siret == old_company.siret
        assert self.employee_record.asp_id == old_company.convention.asp_id

        self.employee_record.wait_for_asp_response(file=faker.unique.asp_batch_filename(), line_number=1, archive=None)
        self.employee_record.process(code="", label="", archive=None)
        self.employee_record.disable()

        # Change SIAE
        self.employee_record.job_application.to_company = new_company
        self.employee_record.job_application.save()
        self.employee_record.refresh_from_db()
        # Reactivate the employee record
        self.employee_record.enable()

        assert self.employee_record.siret == new_company.siret
        assert self.employee_record.asp_id == new_company.convention.asp_id

    def test_state_archived(self):
        approval = self.employee_record.job_application.approval

        # Can't archive while the approval is valid
        assert approval.is_valid()
        with pytest.raises(xworkflows.ForbiddenTransition):
            self.employee_record.archive()

        # Make the approval expires
        approval.start_at = timezone.localdate() - timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)
        approval.end_at = timezone.localdate() - relativedelta(months=1)
        approval.save()
        assert not approval.is_valid()

        self.employee_record.archive()
        # Check correct status and empty archived JSON
        assert self.employee_record.status == Status.ARCHIVED
        assert self.employee_record.archived_json is None

    def test_processed_as_duplicate(self):
        # Check correct status when "manually" forcing status of an employee record
        # with a 3436 error code.
        employee_record_code_3436 = EmployeeRecordWithProfileFactory(
            status=Status.SENT,
            asp_processing_code="3436",
            asp_processing_label="Meh",
        )
        employee_record_other_code = EmployeeRecordWithProfileFactory(
            status=Status.SENT,
            asp_processing_code="3437",
            asp_processing_label="Meh Meh",
        )
        employee_record_other_status = EmployeeRecordWithProfileFactory(
            status=Status.PROCESSED,
            asp_processing_code="3436",
            asp_processing_label="Meh Meh Meh",
        )
        employee_record_code_3436.process(
            code=employee_record_code_3436.asp_processing_code,
            label=employee_record_code_3436.asp_processing_label,
            archive={"codeTraitement": "3436"},
            as_duplicate=True,
        )
        assert employee_record_code_3436.processed_as_duplicate
        assert Status.PROCESSED == employee_record_code_3436.status
        assert "Statut forcé suite à doublon ASP" == employee_record_code_3436.asp_processing_label
        assert employee_record_code_3436.archived_json == {"codeTraitement": "3436"}

        with pytest.raises(ValueError, match="Code needs to be 3436 and not 3437 when as_duplicate=True"):
            employee_record_other_code.process(
                code=employee_record_other_code.asp_processing_code,
                label=employee_record_other_code.asp_processing_label,
                archive=None,
                as_duplicate=True,
            )

        with pytest.raises(xworkflows.InvalidTransitionError):
            employee_record_other_status.process(
                code=employee_record_other_status.asp_processing_code,
                label=employee_record_other_status.asp_processing_label,
                archive=None,
                as_duplicate=True,
            )


class TestEmployeeRecordJobApplicationConstraints:
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
        hiring_date = timezone.localdate() + timedelta(days=7)

        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(hiring_start_at=hiring_date)
        self.employee_record = EmployeeRecord.from_job_application(self.job_application)
        self.employee_record.ready()


class TestEmployeeRecordQueryset:
    def test_for_company(self):
        employee_record_1, employee_record_2 = EmployeeRecordFactory.create_batch(2)

        assert (
            EmployeeRecord.objects.for_company(employee_record_1.job_application.to_company).get() == employee_record_1
        )
        assert (
            EmployeeRecord.objects.for_company(employee_record_2.job_application.to_company).get() == employee_record_2
        )

    def test_for_asp_company(self):
        employee_record_1, employee_record_2 = EmployeeRecordFactory.create_batch(2)
        employee_record_in_antenna = EmployeeRecordFactory(
            job_application__to_company__convention=employee_record_1.job_application.to_company.convention,
            job_application__to_company__source=Company.SOURCE_USER_CREATED,
            job_application__approval=employee_record_1.job_application.approval,
        )

        assert set(EmployeeRecord.objects.for_asp_company(employee_record_1.job_application.to_company)) == {
            employee_record_1,
            employee_record_in_antenna,
        }
        assert (
            EmployeeRecord.objects.for_asp_company(employee_record_2.job_application.to_company).get()
            == employee_record_2
        )

    def test_with_siret_from_asp_source(self):
        employee_record = EmployeeRecordFactory()
        company = employee_record.job_application.to_company
        EmployeeRecordFactory(
            job_application__to_company__convention=company.convention,
            job_application__to_company__source=Company.SOURCE_USER_CREATED,
        )

        assert set(
            EmployeeRecord.objects.with_siret_from_asp_source().values_list("siret_from_asp_source", flat=True)
        ) == {company.siret}


@pytest.mark.parametrize("factory", [BareEmployeeRecordFactory, BareEmployeeRecordUpdateNotificationFactory])
@pytest.mark.parametrize(
    "archive",
    [
        {"Hello": "World"},
        '{"Hello": "World"}',
        {},
        "{}",
        "",
        None,
    ],
    ids=repr,
)
class TestASPExchangeInformationModel:
    def test_set_asp_batch_information(self, factory, archive):
        obj = factory()

        obj.set_asp_batch_information("RIAE_FS_20230123103950.json", 42, archive)
        obj.save()
        obj.refresh_from_db()

        assert obj.asp_batch_file == "RIAE_FS_20230123103950.json"
        assert obj.asp_batch_line_number == 42
        assert obj.archived_json == archive

    @pytest.mark.parametrize(
        "code,expected_code",
        [
            ("0000", "0000"),
            (9999, "9999"),
        ],
        ids=repr,
    )
    def test_set_asp_processing_information(self, factory, archive, code, expected_code):
        obj = factory()

        obj.set_asp_processing_information(code, "The label", archive)
        obj.save()
        obj.refresh_from_db()

        assert obj.asp_processing_code == expected_code
        assert obj.asp_processing_label == "The label"
        assert obj.archived_json == archive


def test_transition_log(faker):
    attributes_mapping = {i[1]: i[0] for i in EmployeeRecordTransitionLog.EXTRA_LOG_ATTRIBUTES}
    tested_transitions = set()

    lifecycle_specs = [
        {
            EmployeeRecordTransition.READY: {"user": EmployerFactory()},
            EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE: {
                "file": faker.asp_batch_filename(),
                "line_number": faker.pyint(),
                "archive": faker.pydict(value_types=[int, str]),
            },
            EmployeeRecordTransition.PROCESS: {
                "code": EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
                "label": faker.sentence(),
                "archive": faker.pydict(value_types=[int, str]),
            },
            EmployeeRecordTransition.DISABLE: {},
            EmployeeRecordTransition.ENABLE: {"user": EmployerFactory()},
            EmployeeRecordTransition.ARCHIVE: {},
            EmployeeRecordTransition.UNARCHIVE_PROCESSED: {},
        },
        {
            EmployeeRecordTransition.READY: {"user": EmployerFactory()},
            EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE: {
                "file": faker.asp_batch_filename(),
                "line_number": faker.pyint(),
                "archive": faker.pydict(value_types=[int, str]),
            },
            EmployeeRecordTransition.REJECT: {
                "code": faker.numerify("33##"),
                "label": faker.sentence(),
                "archive": faker.pydict(value_types=[int, str]),
            },
            EmployeeRecordTransition.ARCHIVE: {},
            EmployeeRecordTransition.UNARCHIVE_REJECTED: {},
        },
        {
            EmployeeRecordTransition.ARCHIVE: {},
            EmployeeRecordTransition.UNARCHIVE_NEW: {},
        },
    ]
    for specs in lifecycle_specs:
        employee_record = EmployeeRecordWithProfileFactory(status=Status.NEW, archivable=True)
        for transition_name, transition_kwargs in specs.items():
            transition_name = "unarchive" if transition_name.startswith("unarchive_") else transition_name
            getattr(employee_record, transition_name)(**transition_kwargs)

        assert employee_record.logs.count() == len(specs)
        for log in employee_record.logs.all():
            for kwargs_name, kwargs_value in specs[log.transition].items():
                assert getattr(log, attributes_mapping[kwargs_name]) == kwargs_value

        tested_transitions |= set(specs.keys())

    assert tested_transitions == {t.name for t in EmployeeRecordWorkflow.transitions}
