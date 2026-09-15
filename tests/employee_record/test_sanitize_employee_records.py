import datetime
import io
import re

import pytest
from django.utils import timezone

from itou.employee_record import models
from itou.employee_record.enums import Status
from itou.employee_record.management.commands import sanitize_employee_records
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return sanitize_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_handle_dry_run(mocker, command, caplog):
    mocker.patch.object(command, "_check_approvals")
    mocker.patch.object(command, "_check_missed_notifications")

    command.handle(wet_run=False)
    assert caplog.messages == [
        "Command launched with wet_run=False",
        "Checking employee records coherence before transferring to ASP",
        "Employee records sanitizing done. Have a great day!",
        "Setting transaction to be rollback as wet_run=False",
    ]


def test_missing_approvals(command, caplog):
    # Check for employee record without approval (through job application)

    employee_record = factories.EmployeeRecordFactory()
    employee_record.job_application.approval = None
    employee_record.job_application.save()

    command.handle(wet_run=True)

    assert models.EmployeeRecord.objects.count() == 0
    assert caplog.messages == [
        "Checking employee records coherence before transferring to ASP",
        "found 1 employee records with missing approval",
        "deleted 1/1 employee records with missing approval",
        "found 0 missed employee records notifications",
        "0/0 employee records were unarchived",
        "Employee records sanitizing done. Have a great day!",
    ]
    assert not models.EmployeeRecord.objects.filter(pk=employee_record.pk).exists()


def test_missed_notifications(command, faker, caplog, snapshot):
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
    command.handle(wet_run=True)
    assert employee_record_with_watched_data_updated_at.update_notifications.count() == 1
    employee_record_with_watched_data_updated_at.refresh_from_db()
    assert employee_record_with_watched_data_updated_at.status != Status.ARCHIVED
    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()


def test_missed_notifications_limit(mocker, snapshot, command, caplog):
    mocker.patch.object(command, "MAX_MISSED_NOTIFICATIONS_CREATED", 2)
    factories.EmployeeRecordFactory.create_batch(
        3,
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
    )

    command.handle(wet_run=True)

    assert models.EmployeeRecordUpdateNotification.objects.count() == 2
    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()
