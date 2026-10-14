import datetime

from django.core.management import call_command
from django.utils import timezone

from itou.employee_record.enums import NotificationStatus
from tests.employee_record import factories


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.scripts.management.commands.resend_employee_record_update_notifications succeeded in "
    )
    return caplog_messages[:-1]


def test_default_run(caplog):
    # New notification: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.NEW, created_at=timezone.now() - datetime.timedelta(days=100)
    )
    # Processed notification: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.PROCESSED, created_at=timezone.now() - datetime.timedelta(days=100)
    )
    # 3446 error: ignored
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3446,
        created_at=timezone.now() - datetime.timedelta(days=100),
    )
    rejected_notification = factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3456,
        created_at=timezone.now() - datetime.timedelta(days=100),
    )
    rejected_notification_with_new_notification = factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.REJECTED,
        asp_processing_code=3455,
        created_at=timezone.now() - datetime.timedelta(days=100),
        employee_record=factories.EmployeeRecordUpdateNotificationFactory().employee_record,
    )
    assert rejected_notification.employee_record.update_notifications.count() == 1
    assert rejected_notification_with_new_notification.employee_record.update_notifications.count() == 2

    call_command("resend_employee_record_update_notifications", wet_run=True)
    assert process_output(caplog.messages) == [
        "Recreated 1 rejected employee record update notifications",
    ]
    # New notification created
    assert rejected_notification.employee_record.update_notifications.count() == 2
    # No new notification created (one already exists)
    assert rejected_notification_with_new_notification.employee_record.update_notifications.count() == 2

    # Mark new notification as rejected to force update_or_create to recreate a new notification if needed
    rejected_notification.employee_record.update_notifications.filter(status=NotificationStatus.NEW).update(
        status=NotificationStatus.REJECTED
    )

    # Recalling it should now ignore rejected_notification
    caplog.clear()
    call_command("resend_employee_record_update_notifications", wet_run=True)
    assert process_output(caplog.messages) == [
        "Recreated 0 rejected employee record update notifications",
    ]
    # No new notification created
    assert rejected_notification.employee_record.update_notifications.count() == 2
    # No new notification created (one already exists)
    assert rejected_notification_with_new_notification.employee_record.update_notifications.count() == 2
