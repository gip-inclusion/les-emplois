import datetime

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from tests.insertion.factories import OrientationFactory


def test_send_orientation_reminder_email(caplog):
    now = timezone.now()

    recent_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS - 1, hours=23, minutes=59)
    reminder_one_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS)
    reminder_two_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS * 2, minutes=1)

    with freeze_time(recent_datetime):
        recent_orientation = OrientationFactory(status=OrientationStatus.PENDING)

    with freeze_time(reminder_one_datetime):
        reminder_one_orientation = OrientationFactory(status=OrientationStatus.PENDING)

        # Statuses other than PENDING are not considered
        [OrientationFactory(status=status) for status in OrientationStatus if status != OrientationStatus.PENDING]

    with freeze_time(reminder_two_datetime):
        reminder_two_orientation = OrientationFactory(status=OrientationStatus.PENDING)

        # Statuses other than PENDING are not considered
        [OrientationFactory(status=status) for status in OrientationStatus if status != OrientationStatus.PENDING]

    with freeze_time(now):
        call_command("set_orientations_last_reminder_email_sent_at", wet_run=True)

    recent_orientation.refresh_from_db()
    reminder_one_orientation.refresh_from_db()
    reminder_two_orientation.refresh_from_db()

    assert "Updated 1 orientations between 10 and 20 days old." in caplog.messages
    assert "Updated 1 orientations older than 20 days old." in caplog.messages

    assert recent_orientation.last_reminder_email_sent_at is None
    assert reminder_one_orientation.last_reminder_email_sent_at == reminder_one_datetime + datetime.timedelta(
        days=Orientation.REMINDER_EMAIL_DELAY_DAYS
    )
    assert reminder_two_orientation.last_reminder_email_sent_at == reminder_two_datetime + datetime.timedelta(
        days=Orientation.REMINDER_EMAIL_DELAY_DAYS * 2
    )
