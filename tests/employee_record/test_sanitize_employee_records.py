import datetime
import io

import pytest

from itou.employee_record import models
from itou.employee_record.enums import Status
from itou.employee_record.management.commands import sanitize_employee_records
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return sanitize_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_handle_dry_run_option(mocker, command):
    mocker.patch.object(command, "_check_approvals")
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
    # Approval() updated after the last employee record snapshot are what we want
    employee_record_before_approval = factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        updated_at=faker.date_time_between(end_date="-1y", tzinfo=datetime.UTC),
        job_application__approval__updated_at=faker.date_time_between(
            start_date="-1y", end_date="-1d", tzinfo=datetime.UTC
        ),
    )

    # But not the Approval() updated before the last employee record snapshot
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        updated_at=faker.date_time_between(start_date="-1y", end_date="-1d", tzinfo=datetime.UTC),
        job_application__approval__updated_at=faker.date_time_between(end_date="-1y", tzinfo=datetime.UTC),
    )

    # Approval() that can no longer be prolonged are ignored
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        job_application__approval__expired=True,
        job_application__approval__created_at=faker.future_datetime(tzinfo=datetime.UTC),
    )

    # EmployeeRecordUpdateNotification() should be taken into account
    factories.EmployeeRecordUpdateNotificationFactory(
        employee_record__status=models.Status.ARCHIVED,
        employee_record__job_application__approval__created_at=faker.future_datetime(
            end_date="+1d", tzinfo=datetime.UTC
        ),
        created_at=faker.date_time_between(start_date="+1d", end_date="+30d", tzinfo=datetime.UTC),
    )

    # Various cases are now set up, finally check the behavior
    command._check_missed_notifications(dry_run=False)
    assert employee_record_before_approval.update_notifications.count() == 1
    employee_record_before_approval.refresh_from_db()
    assert employee_record_before_approval.status != Status.ARCHIVED
    assert command.stdout.getvalue().split("\n") == [
        "* Checking missing employee records notifications:",
        " - found 1 missing notification(s)",
        " - 1 notification(s) created",
        " - done!",
        "",
    ]


def test_missed_notifications_limit(faker, mocker, snapshot, command):
    mocker.patch.object(command, "MAX_MISSED_NOTIFICATIONS_CREATED", 2)
    factories.EmployeeRecordFactory.create_batch(
        3,
        status=models.Status.ARCHIVED,
        updated_at=faker.date_time_between(end_date="-1y", tzinfo=datetime.UTC),
        job_application__approval__updated_at=faker.date_time_between(
            start_date="-1y", end_date="-1d", tzinfo=datetime.UTC
        ),
    )

    command._check_missed_notifications(dry_run=False)

    assert models.EmployeeRecordUpdateNotification.objects.count() == 2
    assert command.stdout.getvalue() == snapshot
