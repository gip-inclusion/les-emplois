import collections

from django.core.management import call_command
from pytest_django.asserts import assertQuerySetEqual

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import (
    EmployeeRecord,
    EmployeeRecordBatch,
    EmployeeRecordTransition,
    EmployeeRecordUpdateNotification,
)
from tests.employee_record import factories


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.employee_record.management.commands.migrate_employee_record_update_notifications "
        "succeeded in "
    )
    return caplog_messages[:-1]


def test_management_command_default_run(caplog, faker):
    employee_record = factories.EmployeeRecordFactory()
    new_notification_ignored = factories.EmployeeRecordUpdateNotificationFactory(
        employee_record=employee_record, status=NotificationStatus.NEW
    )
    processed_notification = factories.EmployeeRecordUpdateNotificationFactory(
        employee_record=employee_record,
        status=NotificationStatus.PROCESSED,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
        asp_batch_line_number=1,
        archived_json={"notification": "processed_notification"},
        asp_processing_label="Something processed",
        asp_processing_code=EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
    )
    rejected_notification_not_last = factories.EmployeeRecordUpdateNotificationFactory(
        employee_record=employee_record,
        status=NotificationStatus.REJECTED,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
        asp_batch_line_number=2,
        archived_json={"notification": "rejected_notification_not_last"},
        asp_processing_label="Something processed",
        asp_processing_code=faker.numerify("32##"),
    )
    sent_notification_ignored = factories.EmployeeRecordUpdateNotificationFactory(
        employee_record=employee_record,
        status=NotificationStatus.SENT,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
        asp_batch_line_number=3,
        archived_json={"notification": "sent_notification_ignored"},
    )
    rejected_notification_last = factories.EmployeeRecordUpdateNotificationFactory(
        employee_record=employee_record,
        status=NotificationStatus.REJECTED,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
        asp_batch_line_number=4,
        archived_json={"notification": "rejected_notification_last"},
        asp_processing_label="Something processed",
        asp_processing_code=faker.numerify("32##"),
    )

    call_command("migrate_employee_record_update_notifications", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting migrating employee records - starting at pk=0",
        "Migrated 2 EmployeeRecordUpdateNotification to 6 EmployeeRecordTransitionLog",
        f"Stored last migrated employee record - pk={employee_record.pk}",
    ]
    assertQuerySetEqual(
        EmployeeRecordUpdateNotification.objects.all(),
        [new_notification_ignored.pk, sent_notification_ignored.pk, rejected_notification_last.pk],
        transform=lambda obj: obj.pk,
        ordered=False,
    )
    # Record status was left intact
    employee_record.refresh_from_db()
    assert employee_record.status == Status.NEW
    logs = list(employee_record.logs.all())
    assert all(log.recovered for log in logs)
    assert len(logs) == 6
    assert collections.Counter(log.transition for log in logs) == {
        EmployeeRecordTransition.SCHEDULE_MODIFICATION: 2,
        EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE: 2,
        EmployeeRecordTransition.PROCESS_MODIFICATION: 1,
        EmployeeRecordTransition.REJECT_MODIFICATION: 1,
    }
    logged_archives = [log.archived_json for log in logs]
    assert processed_notification.archived_json in logged_archives
    assert rejected_notification_not_last.archived_json in logged_archives
    assert rejected_notification_last.archived_json not in logged_archives

    # Call a second time, with include_last_rejected option
    caplog.clear()
    call_command("migrate_employee_record_update_notifications", wet_run=True, include_last_rejected=True)
    assert process_output(caplog.messages) == [
        "Starting migrating employee records - starting at pk=0",
        f"Updating employee_record={employee_record.pk} status to MODIFICATION_REJECTED",
        "Migrated 1 EmployeeRecordUpdateNotification to 3 EmployeeRecordTransitionLog",
        f"Stored last migrated employee record - pk={employee_record.pk}",
    ]

    assertQuerySetEqual(
        EmployeeRecordUpdateNotification.objects.all(),
        [new_notification_ignored.pk, sent_notification_ignored.pk],
        transform=lambda obj: obj.pk,
        ordered=False,
    )
    employee_record.refresh_from_db()
    assert employee_record.status == Status.MODIFICATION_REJECTED
    logs = list(employee_record.logs.all())
    assert all(log.recovered for log in logs)
    assert len(logs) == 9
    assert collections.Counter(log.transition for log in logs) == {
        EmployeeRecordTransition.SCHEDULE_MODIFICATION: 3,
        EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE: 3,
        EmployeeRecordTransition.PROCESS_MODIFICATION: 1,
        EmployeeRecordTransition.REJECT_MODIFICATION: 2,
    }
    logged_archives = [log.archived_json for log in logs]
    assert processed_notification.archived_json in logged_archives
    assert rejected_notification_not_last.archived_json in logged_archives
    assert rejected_notification_last.archived_json in logged_archives


def test_batch_size_continue(caplog, mocker):
    mocker.patch(
        "itou.employee_record.management.commands.migrate_employee_record_update_notifications.Command.BATCH_SIZE", 1
    )
    first_employee_record = factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.PROCESSED,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
    ).employee_record
    factories.EmployeeRecordUpdateNotificationFactory(
        employee_record=first_employee_record,
        status=NotificationStatus.REJECTED,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
    )
    second_employee_record = factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.PROCESSED,
        asp_batch_file=EmployeeRecordBatch.get_remote_path(),
    ).employee_record

    # First call handle first_employee_record but leaves one rejected notification
    call_command("migrate_employee_record_update_notifications", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting migrating employee records - starting at pk=0",
        "Migrated 1 EmployeeRecordUpdateNotification to 3 EmployeeRecordTransitionLog",
        f"Stored last migrated employee record - pk={first_employee_record.pk}",
    ]

    # Second call starts after first_employee_record.pk and handle the second one
    caplog.clear()
    call_command("migrate_employee_record_update_notifications", wet_run=True)
    assert process_output(caplog.messages) == [
        f"Starting migrating employee records - starting at pk={first_employee_record.pk}",
        "Migrated 1 EmployeeRecordUpdateNotification to 3 EmployeeRecordTransitionLog",
        f"Stored last migrated employee record - pk={second_employee_record.pk}",
    ]

    # Third call finds not employee_record after the second one and resets the cached key
    caplog.clear()
    call_command("migrate_employee_record_update_notifications", wet_run=True)
    assert process_output(caplog.messages) == [
        f"Starting migrating employee records - starting at pk={second_employee_record.pk}",
        "Migrated 0 EmployeeRecordUpdateNotification to 0 EmployeeRecordTransitionLog",
        "Stored last migrated employee record - pk=0",
    ]
