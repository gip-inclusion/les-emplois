import datetime
import io
import random
import re

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.employee_record import models
from itou.employee_record.enums import Status
from itou.employee_record.management.commands import sanitize_employee_records
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return sanitize_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.employee_record.management.commands.sanitize_employee_records succeeded in "
    )
    return [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog_messages[:-1]]


def test_handle_dry_run(mocker, caplog):
    mocker.patch.object(sanitize_employee_records.Command, "_check_approvals")
    mocker.patch.object(sanitize_employee_records.Command, "_check_missed_notifications")
    call_command("sanitize_employee_records", wet_run=False)

    assert process_output(caplog.messages) == [
        "Command launched with wet_run=False",
        "Checking employee records coherence before transferring to ASP",
        "Employee records sanitizing done. Have a great day!",
        "Setting transaction to be rollback as wet_run=False",
    ]


def test_missing_approvals(caplog):
    # Check for employee record without approval (through job application)

    employee_record = factories.EmployeeRecordFactory()
    employee_record.job_application.approval = None
    employee_record.job_application.save()

    call_command("sanitize_employee_records", wet_run=True)

    assert models.EmployeeRecord.objects.count() == 0
    assert process_output(caplog.messages) == [
        "Checking employee records coherence before transferring to ASP",
        "found 1 employee records with missing approval",
        "deleted 1/1 employee records with missing approval",
        "found 0 missed employee records notifications",
        "0/0 employee records were unarchived",
        "Employee records sanitizing done. Have a great day!",
    ]
    assert not models.EmployeeRecord.objects.filter(pk=employee_record.pk).exists()


def test_missed_notifications(faker, caplog, snapshot):
    # Approval() with watched_data_updated_at are what we want
    employee_record_with_watched_data_updated_at = factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
    )

    # But not Approval() without watched_data_updated_at
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        watched_data_updated_at=None,
    )

    # Approval() that can no longer be prolonged are ignored, even with watched_data_updated_at
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
        job_application__approval__expired=True,
        job_application__approval__created_at=faker.future_datetime(tzinfo=datetime.UTC),
    )

    # Various cases are now set up, finally check the behavior
    call_command("sanitize_employee_records", wet_run=True)
    assert employee_record_with_watched_data_updated_at.update_notifications.count() == 0  # No notifications created
    employee_record_with_watched_data_updated_at.refresh_from_db()
    assert employee_record_with_watched_data_updated_at.status != Status.ARCHIVED
    assert process_output(caplog.messages) == snapshot()


def test_missed_notifications_limit(mocker, snapshot, caplog):
    mocker.patch.object(sanitize_employee_records.Command, "MAX_MISSED_NOTIFICATIONS_CREATED", 2)
    factories.EmployeeRecordFactory.create_batch(
        3,
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
    )

    call_command("sanitize_employee_records", wet_run=True)

    assert models.EmployeeRecordUpdateNotification.objects.count() == 0  # No notifications created
    assert process_output(caplog.messages) == snapshot()


def test_schedule_modifications():
    processed_employee_record_without_flag = factories.EmployeeRecordFactory(
        status=models.Status.PROCESSED,
    )
    processed_employee_record_with_flag = factories.EmployeeRecordFactory(
        status=models.Status.PROCESSED,
        watched_data_updated_at=timezone.now(),
    )
    other_status = random.choice(
        [status for status in models.Status if status not in (Status.PROCESSED, Status.ARCHIVED)]
    )
    not_processed_employee_record_with_flag = factories.EmployeeRecordFactory(
        status=other_status,
        watched_data_updated_at=timezone.now(),
    )
    call_command("sanitize_employee_records", wet_run=True)

    processed_employee_record_without_flag.refresh_from_db()
    assert processed_employee_record_without_flag.status == Status.PROCESSED

    processed_employee_record_with_flag.refresh_from_db()
    assert processed_employee_record_with_flag.status == Status.MODIFICATION_PENDING

    not_processed_employee_record_with_flag.refresh_from_db()
    assert not_processed_employee_record_with_flag.status == other_status
