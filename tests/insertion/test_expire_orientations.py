import datetime

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from tests.insertion.factories import OrientationFactory


def test_expire_orientations(caplog, snapshot):
    now = timezone.now()

    recent_datetime = now - datetime.timedelta(days=6, hours=23, minutes=59)
    old_datetime = now - datetime.timedelta(days=Orientation.PENDING_EXPIRATION_PERIOD_DAYS, minutes=1)
    older_datetime = now - datetime.timedelta(days=Orientation.PROCESSING_EXPIRATION_PERIOD_DAYS, minutes=1)

    with freeze_time(recent_datetime):
        recent_pending_orientation = OrientationFactory(status=OrientationStatus.PENDING)
        recent_processing_orientation = OrientationFactory(status=OrientationStatus.PROCESSING)

    with freeze_time(old_datetime):
        old_pending_orientation = OrientationFactory(status=OrientationStatus.PENDING)
        old_processing_orientation = OrientationFactory(status=OrientationStatus.PROCESSING)

    with freeze_time(older_datetime):
        older_pending_orientation = OrientationFactory(status=OrientationStatus.PENDING)
        older_processing_orientation = OrientationFactory(status=OrientationStatus.PROCESSING)
        accepted_orientation = OrientationFactory(status=OrientationStatus.ACCEPTED)
        refused_orientation = OrientationFactory(status=OrientationStatus.REFUSED)
        expired_orientation = OrientationFactory(status=OrientationStatus.EXPIRED)

    with freeze_time(now):
        with assertSnapshotQueries(snapshot(name="sql")):
            call_command("expire_orientations", wet_run=True)

    recent_pending_orientation.refresh_from_db()
    recent_processing_orientation.refresh_from_db()
    old_pending_orientation.refresh_from_db()
    old_processing_orientation.refresh_from_db()
    older_pending_orientation.refresh_from_db()
    older_processing_orientation.refresh_from_db()
    accepted_orientation.refresh_from_db()
    refused_orientation.refresh_from_db()
    expired_orientation.refresh_from_db()

    assert "Found 3 orientations to expire." in caplog.messages

    # Too recent to be expired
    assert recent_pending_orientation.status == OrientationStatus.PENDING
    assert recent_processing_orientation.status == OrientationStatus.PROCESSING
    assert old_processing_orientation.status == OrientationStatus.PROCESSING
    for orientation in [recent_pending_orientation, recent_processing_orientation, old_processing_orientation]:
        assert orientation.updated_at != now

    # Expired
    assert old_pending_orientation.status == OrientationStatus.EXPIRED
    assert older_pending_orientation.status == OrientationStatus.EXPIRED
    assert older_processing_orientation.status == OrientationStatus.EXPIRED
    for orientation in [old_pending_orientation, older_pending_orientation, older_processing_orientation]:
        assert orientation.updated_at == now

    # Accepted, refused and expired orientations did not change
    assert accepted_orientation.status == OrientationStatus.ACCEPTED
    assert refused_orientation.status == OrientationStatus.REFUSED
    assert expired_orientation.status == OrientationStatus.EXPIRED
    for orientation in [accepted_orientation, refused_orientation, expired_orientation]:
        assert orientation.updated_at != now


def test_expire_orientations_sequentially(caplog):
    now = timezone.now()
    old_datetime = now - datetime.timedelta(days=Orientation.PENDING_EXPIRATION_PERIOD_DAYS, minutes=1)
    older_datetime = now - datetime.timedelta(days=Orientation.PROCESSING_EXPIRATION_PERIOD_DAYS, minutes=1)

    with freeze_time(old_datetime):
        old_pending_orientation = OrientationFactory(status=OrientationStatus.PENDING)

    with freeze_time(older_datetime):
        older_pending_orientation = OrientationFactory(status=OrientationStatus.PENDING)
        older_processing_orientation = OrientationFactory(status=OrientationStatus.PROCESSING)

    call_command("expire_orientations", wet_run=True, limit=1)
    assert set(Orientation.objects.filter(status=OrientationStatus.EXPIRED).values_list("pk", flat=True)) == {
        older_pending_orientation.pk
    }
    call_command("expire_orientations", wet_run=True, limit=1)
    assert set(Orientation.objects.filter(status=OrientationStatus.EXPIRED).values_list("pk", flat=True)) == {
        older_pending_orientation.pk,
        older_processing_orientation.pk,
    }
    call_command("expire_orientations", wet_run=True, limit=2)
    assert set(Orientation.objects.filter(status=OrientationStatus.EXPIRED).values_list("pk", flat=True)) == {
        older_processing_orientation.pk,
        older_pending_orientation.pk,
        old_pending_orientation.pk,
    }
