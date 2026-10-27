import datetime
import re

from django.core.management import call_command
from django.utils import timezone

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecord
from tests.employee_record import factories


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.scripts.management.commands.resend_employee_record_with_3446_notification succeeded "
    )
    return [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog_messages[:-1]]


def test_default_run(caplog, faker):
    # New notification: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.NEW,
        employee_record__status=Status.PROCESSED,
        employee_record__processed_at=timezone.now() - datetime.timedelta(days=1),
    )
    # Processed notification: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.PROCESSED,
        employee_record__status=Status.PROCESSED,
        employee_record__processed_at=timezone.now() - datetime.timedelta(days=1),
    )
    # Not 3446 error: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3456,
        employee_record__status=Status.PROCESSED,
        employee_record__processed_at=timezone.now() - datetime.timedelta(days=1),
    )
    # Archived record: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3446,
        employee_record__status=Status.ARCHIVED,
        employee_record__processed_at=timezone.now() - datetime.timedelta(days=1),
    )
    # Processed after the notification: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3446,
        employee_record__status=Status.PROCESSED,
        employee_record__processed_at=timezone.now() + datetime.timedelta(days=1),
    )
    rejected_notification = factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3446,
        employee_record__status=Status.PROCESSED,
        employee_record__processed_at=timezone.now() - datetime.timedelta(days=1),
    )
    common_record = rejected_notification.employee_record
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3446,
        employee_record=common_record,
    )
    rejected_notification_with_borked_data = factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3446,
        employee_record__status=Status.PROCESSED,
        employee_record__processed_at=timezone.now() - datetime.timedelta(days=1),
        employee_record__job_application__job_seeker__title="",  # This should break the ready call
    )
    assert EmployeeRecord.objects.filter(status=Status.READY).count() == 0
    call_command("resend_employee_record_with_3446_notification", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting resending employee records - starting at pk=0",
        "[EMPLOYEE RECORD] performed transition EmployeeRecordWorkflow.ready (PROCESSED -> READY)",
        f"Could not transition employee_record={rejected_notification_with_borked_data.employee_record.pk} to READY",
        "Changed 1 employee records to READY status",
        f"Stored last migrated employee record notification - pk={rejected_notification_with_borked_data.pk}",
    ]
    assert EmployeeRecord.objects.filter(status=Status.READY).count() == 1
    common_record.refresh_from_db()
    assert common_record.status == Status.READY

    # Recalling it should reset the cache key
    caplog.clear()
    call_command("resend_employee_record_with_3446_notification", wet_run=True)
    assert process_output(caplog.messages) == [
        f"Starting resending employee records - starting at pk={rejected_notification_with_borked_data.pk}",
        "Changed 0 employee records to READY status",
        "Stored last migrated employee record notification - pk=0",
    ]

    # Drop borked notification to simplify following calls
    rejected_notification_with_borked_data.delete()

    # Recalling it should now ignore the record since it is now in READY status
    caplog.clear()
    call_command("resend_employee_record_with_3446_notification", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting resending employee records - starting at pk=0",
        "Changed 0 employee records to READY status",
        "Stored last migrated employee record notification - pk=0",
    ]

    # Simulate proper processing
    common_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)
    common_record.process(code="0000", label="All good", archive={})

    # Recalling it should now ignore the record since its processed_at is more recent than the rejected notifications
    caplog.clear()
    call_command("resend_employee_record_with_3446_notification", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting resending employee records - starting at pk=0",
        "Changed 0 employee records to READY status",
        "Stored last migrated employee record notification - pk=0",
    ]
