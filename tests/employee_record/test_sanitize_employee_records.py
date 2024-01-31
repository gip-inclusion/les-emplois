import datetime
import io

import pytest

from itou.employee_record import models
from itou.employee_record.enums import Status
from itou.employee_record.management.commands import sanitize_employee_records
from tests.approvals import factories as approvals_factories
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return sanitize_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_handle_dry_run_option(mocker, command):
    mocker.patch.object(command, "_check_approvals")
    mocker.patch.object(command, "_check_jobseeker_profiles")
    mocker.patch.object(command, "_check_3436_error_code")
    mocker.patch.object(command, "_check_missed_notifications")

    command.handle(dry_run=True)
    assert command.stdout.getvalue().split("\n") == [
        "+ Checking employee records coherence before transferring to ASP",
        " - DRY-RUN mode: not fixing, just reporting",
        "+ Employee records sanitizing done. Have a great day!",
        "",
    ]


def test_3436_errors_check(command):
    # Check for 3436 errors fix (ASP duplicates)

    employee_record = factories.EmployeeRecordWithProfileFactory(
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_DUPLICATE_ERROR_CODE,
    )

    command._check_3436_error_code(dry_run=False)

    # Exterminate 3436s
    employee_record.refresh_from_db()
    assert employee_record.status == models.Status.PROCESSED
    assert employee_record.processed_as_duplicate is True
    assert command.stdout.getvalue().split("\n") == [
        "* Checking REJECTED employee records with error 3436 (duplicates):",
        " - found 1 error(s)",
        " - fixing 3436 errors: forcing status to PROCESSED",
        " - done!",
        "",
    ]


def test_profile_errors_check(command):
    # Check for profile errors during sanitize_employee_records

    employee_record = factories.EmployeeRecordFactory(status=models.Status.PROCESSED)

    command._check_jobseeker_profiles(dry_run=False)

    employee_record.refresh_from_db()
    assert employee_record.status == models.Status.DISABLED
    assert command.stdout.getvalue().split("\n") == [
        "* Checking employee records job seeker profile:",
        " - found 1 job seeker profile(s) without HEXA address",
        " - fixing missing address in profiles: switching status to DISABLED",
        " - done!",
        "",
    ]


def test_missing_approvals(command):
    # Check for employee record without approval (through job application)

    employee_record = factories.EmployeeRecordFactory()
    employee_record.job_application.approval = None
    employee_record.job_application.save()

    command._check_approvals(dry_run=False)

    assert models.EmployeeRecord.objects.count() == 0
    assert command.stdout.getvalue().split("\n") == [
        "* Checking missing employee records approval:",
        " - found 1 missing approval(s)",
        " - fixing missing approvals: DELETING employee records",
        " - done!",
        "",
    ]


def test_missed_notifications(command, faker):
    # Prolongation() after the last employee record snapshot are what we want
    employee_record_with_prolongation = factories.EmployeeRecordFactory(status=models.Status.ARCHIVED)
    approvals_factories.ProlongationFactory(approval=employee_record_with_prolongation.job_application.approval)

    # Approval() created after the last employee record snapshot are also what we want
    employee_record_before_approval_creation = factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        job_application__approval__created_at=faker.future_datetime(tzinfo=datetime.UTC),  # So it pass the date filter
    )

    # Prolongation() before the last employee record snapshot are ignored
    approvals_factories.ProlongationFactory(
        approval=factories.EmployeeRecordFactory(
            status=models.Status.ARCHIVED,
            job_application__approval__created_at=faker.date_time_between(end_date="-1y", tzinfo=datetime.UTC),
        ).job_application.approval,
        created_at=faker.date_time_between(start_date="-1y", end_date="-1d", tzinfo=datetime.UTC),
    )

    # Approval() that can no longer be prolonged are ignored
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        job_application__approval__expired=True,
        job_application__approval__created_at=faker.future_datetime(tzinfo=datetime.UTC),
    )

    # All Suspension() are ignored
    approvals_factories.SuspensionFactory(
        approval=factories.EmployeeRecordFactory(status=models.Status.ARCHIVED).job_application.approval
    )

    # EmployeeRecordUpdateNotification() should be taken into account
    factories.EmployeeRecordUpdateNotificationFactory(
        employee_record__status=models.Status.ARCHIVED,
        employee_record__job_application__approval__created_at=faker.future_datetime(
            end_date="+1d", tzinfo=datetime.UTC
        ),
        created_at=faker.date_time_between(start_date="+1d", end_date="+30d", tzinfo=datetime.UTC),
    )

    wrongly_archived_employee_records = [employee_record_with_prolongation, employee_record_before_approval_creation]
    # Various cases are now set up, finally check the behavior
    command._check_missed_notifications(dry_run=False)
    for employee_record in wrongly_archived_employee_records:
        assert employee_record.update_notifications.count() == 1
        employee_record.refresh_from_db()
        assert employee_record.status != Status.ARCHIVED
    assert command.stdout.getvalue().split("\n") == [
        "* Checking missing employee records notifications:",
        " - found 2 missing notification(s)",
        " - 2 notification(s) created",
        " - done!",
        "",
    ]
