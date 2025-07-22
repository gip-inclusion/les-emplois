from django.utils import timezone

from itou.analytics import archive, models
from itou.utils.constants import DAYS_OF_INACTIVITY, INACTIVITY_PERIOD
from tests.archive.factories import (
    AnonymizedApplicationFactory,
    AnonymizedApprovalFactory,
    AnonymizedCancelledApprovalFactory,
    AnonymizedGEIQEligibilityDiagnosisFactory,
    AnonymizedJobSeekerFactory,
    AnonymizedProfessionalFactory,
    AnonymizedSIAEEligibilityDiagnosisFactory,
)
from tests.users.factories import EmployerFactory, JobSeekerFactory


def test_datum_name_value():
    assert models.DatumCode.ANONYMIZED_PROFESSIONALS_DELETED.value == "ARCH-001"
    assert models.DatumCode.ANONYMIZED_PROFESSIONALS_NOT_DELETED.value == "ARCH-002"
    assert models.DatumCode.ANONYMIZED_JOB_SEEKERS.value == "ARCH-003"
    assert models.DatumCode.ANONYMIZED_APPLICATIONS.value == "ARCH-004"
    assert models.DatumCode.ANONYMIZED_APPROVALS.value == "ARCH-005"
    assert models.DatumCode.ANONYMIZED_CANCELLED_APPROVALS.value == "ARCH-006"
    assert models.DatumCode.ANONYMIZED_IAE_ELIGIBILITY_DIAGNOSIS.value == "ARCH-007"
    assert models.DatumCode.ANONYMIZED_GEIQ_ELIGIBILITY_DIAGNOSIS.value == "ARCH-008"
    assert models.DatumCode.NOTIFIED_JOB_SEEKERS.value == "ARCH-009"
    assert models.DatumCode.NOTIFIED_PROFESSIONALS.value == "ARCH-010"
    assert models.DatumCode.NOTIFIABLE_JOB_SEEKERS.value == "ARCH-011"
    assert models.DatumCode.NOTIFIABLE_PROFESSIONALS.value == "ARCH-012"


def test_collect_archive_data_return_all_codes():
    assert archive.collect_archive_data().keys() == {
        models.DatumCode.ANONYMIZED_PROFESSIONALS_DELETED,
        models.DatumCode.ANONYMIZED_PROFESSIONALS_NOT_DELETED,
        models.DatumCode.ANONYMIZED_JOB_SEEKERS,
        models.DatumCode.ANONYMIZED_APPLICATIONS,
        models.DatumCode.ANONYMIZED_APPROVALS,
        models.DatumCode.ANONYMIZED_CANCELLED_APPROVALS,
        models.DatumCode.ANONYMIZED_IAE_ELIGIBILITY_DIAGNOSIS,
        models.DatumCode.ANONYMIZED_GEIQ_ELIGIBILITY_DIAGNOSIS,
        models.DatumCode.NOTIFIED_JOB_SEEKERS,
        models.DatumCode.NOTIFIED_PROFESSIONALS,
        models.DatumCode.NOTIFIABLE_JOB_SEEKERS,
        models.DatumCode.NOTIFIABLE_PROFESSIONALS,
    }


def test_collect_archive_data_when_no_data_exists():
    assert archive.collect_archive_data() == {
        models.DatumCode.ANONYMIZED_PROFESSIONALS_DELETED: 0,
        models.DatumCode.ANONYMIZED_PROFESSIONALS_NOT_DELETED: 0,
        models.DatumCode.ANONYMIZED_JOB_SEEKERS: 0,
        models.DatumCode.ANONYMIZED_APPLICATIONS: 0,
        models.DatumCode.ANONYMIZED_APPROVALS: 0,
        models.DatumCode.ANONYMIZED_CANCELLED_APPROVALS: 0,
        models.DatumCode.ANONYMIZED_IAE_ELIGIBILITY_DIAGNOSIS: 0,
        models.DatumCode.ANONYMIZED_GEIQ_ELIGIBILITY_DIAGNOSIS: 0,
        models.DatumCode.NOTIFIED_JOB_SEEKERS: 0,
        models.DatumCode.NOTIFIED_PROFESSIONALS: 0,
        models.DatumCode.NOTIFIABLE_JOB_SEEKERS: 0,
        models.DatumCode.NOTIFIABLE_PROFESSIONALS: 0,
    }


def test_collect_archive_data_with_data():
    AnonymizedProfessionalFactory()
    EmployerFactory.create_batch(2, notified_days_ago=1, email=None)
    AnonymizedJobSeekerFactory.create_batch(3)
    AnonymizedApplicationFactory.create_batch(4)
    AnonymizedApprovalFactory.create_batch(5)
    AnonymizedCancelledApprovalFactory.create_batch(6)
    AnonymizedSIAEEligibilityDiagnosisFactory.create_batch(7)
    AnonymizedGEIQEligibilityDiagnosisFactory.create_batch(8)
    JobSeekerFactory.create_batch(9, joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1)
    EmployerFactory.create_batch(10, joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1)
    JobSeekerFactory.create_batch(11, joined_days_ago=DAYS_OF_INACTIVITY)
    EmployerFactory.create_batch(12, joined_days_ago=DAYS_OF_INACTIVITY, last_login=timezone.now() - INACTIVITY_PERIOD)

    assert archive.collect_archive_data() == {
        models.DatumCode.ANONYMIZED_PROFESSIONALS_DELETED: 1,
        models.DatumCode.ANONYMIZED_PROFESSIONALS_NOT_DELETED: 2,
        models.DatumCode.ANONYMIZED_JOB_SEEKERS: 3,
        models.DatumCode.ANONYMIZED_APPLICATIONS: 4,
        models.DatumCode.ANONYMIZED_APPROVALS: 5,
        models.DatumCode.ANONYMIZED_CANCELLED_APPROVALS: 6,
        models.DatumCode.ANONYMIZED_IAE_ELIGIBILITY_DIAGNOSIS: 7,
        models.DatumCode.ANONYMIZED_GEIQ_ELIGIBILITY_DIAGNOSIS: 8,
        models.DatumCode.NOTIFIED_JOB_SEEKERS: 9,
        models.DatumCode.NOTIFIED_PROFESSIONALS: 10,
        models.DatumCode.NOTIFIABLE_JOB_SEEKERS: 11,
        models.DatumCode.NOTIFIABLE_PROFESSIONALS: 12,
    }
