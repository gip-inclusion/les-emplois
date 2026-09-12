import datetime

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation, OrientationProcessLink
from tests.insertion.factories import OrientationFactory


def test_send_orientation_reminder_email(caplog, snapshot, django_capture_on_commit_callbacks, mailoutbox):
    now = timezone.now()

    no_reminder_datetime = now - datetime.timedelta(days=9, hours=23, minutes=59)
    reminder_one_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS, minutes=1)
    reminder_two_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS * 2, minutes=1)

    with freeze_time(no_reminder_datetime):
        recent_orientation = OrientationFactory(status=OrientationStatus.PENDING)

    with freeze_time(reminder_one_datetime):
        reminder_one_orientation = OrientationFactory(status=OrientationStatus.PENDING)

        # Statuses other than PENDING are not considered
        [OrientationFactory(status=status) for status in OrientationStatus if status != OrientationStatus.PENDING]

    with freeze_time(reminder_two_datetime):
        reminder_two_orientation = OrientationFactory(
            status=OrientationStatus.PENDING, last_reminder_email_sent_at=reminder_one_datetime
        )

        # A reminder has been sent recently
        OrientationFactory(status=OrientationStatus.PENDING, last_reminder_email_sent_at=no_reminder_datetime)

        # Statuses other than PENDING are not considered
        [OrientationFactory(status=status) for status in OrientationStatus if status != OrientationStatus.PENDING]

    with freeze_time(now):
        with assertSnapshotQueries(snapshot(name="sql")):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("send_orientations_reminder_emails", wet_run=True)

    recent_orientation.refresh_from_db()
    reminder_one_orientation.refresh_from_db()
    reminder_two_orientation.refresh_from_db()

    assert "Sent reminder emails for 2 orientations." in caplog.messages
    assert len(mailoutbox) == 2

    assert recent_orientation.last_reminder_email_sent_at is None
    assert reminder_one_orientation.last_reminder_email_sent_at == now
    assert reminder_two_orientation.last_reminder_email_sent_at == now

    assert OrientationProcessLink.objects.count() == 2


def test_send_reminders_sequentially():
    now = timezone.now()
    reminder_one_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS, minutes=1)
    reminder_two_datetime = now - datetime.timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS * 2, minutes=1)

    with freeze_time(reminder_one_datetime):
        reminder_one_orientation = OrientationFactory(status=OrientationStatus.PENDING)

    with freeze_time(reminder_two_datetime):
        reminder_two_orientation = OrientationFactory(status=OrientationStatus.PENDING)

    call_command("send_orientations_reminder_emails", wet_run=True, limit=1)
    assert set(Orientation.objects.filter(last_reminder_email_sent_at__isnull=False).values_list("pk", flat=True)) == {
        reminder_two_orientation.pk
    }
    call_command("send_orientations_reminder_emails", wet_run=True, limit=1)
    assert set(Orientation.objects.filter(last_reminder_email_sent_at__isnull=False).values_list("pk", flat=True)) == {
        reminder_two_orientation.pk,
        reminder_one_orientation.pk,
    }
