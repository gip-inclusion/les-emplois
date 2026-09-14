import datetime
import random

from dateutil.relativedelta import relativedelta
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from tests.files.factories import FileFactory
from tests.insertion.factories import OrientationFactory


def test_delete_orientations_documents(caplog, snapshot):
    now = timezone.now()

    recent_datetime = now - datetime.timedelta(days=6, hours=23, minutes=59)
    old_datetime = now - relativedelta(months=Orientation.DOCUMENTS_EXPIRATION_MONTHS, minutes=1)

    with freeze_time(recent_datetime):
        recent_orientation = OrientationFactory(status=OrientationStatus.ACCEPTED)
        recent_orientation.documents.set([FileFactory()])

    with freeze_time(old_datetime):
        old_accepted_orientation = OrientationFactory(status=OrientationStatus.ACCEPTED)
        old_accepted_orientation.documents.set([FileFactory()])

        old_orientation_other_state = OrientationFactory(
            status=random.choice(
                [status for status in OrientationStatus.values if status != OrientationStatus.ACCEPTED.value]
            )
        )
        old_orientation_other_state.documents.set([FileFactory()])

    with freeze_time(now):
        with assertSnapshotQueries(snapshot(name="sql")):
            call_command("delete_orientations_documents", wet_run=True)

    recent_orientation.refresh_from_db()
    old_accepted_orientation.refresh_from_db()
    old_orientation_other_state.refresh_from_db()

    assert "Found and deleted attached documents for 2 orientations." in caplog.messages

    # Too recent to be deleted
    assert recent_orientation.documents.exists()

    # Deleted
    assert not old_accepted_orientation.documents.exists()
    assert not old_orientation_other_state.documents.exists()

    # updated_at was not changed - it is displayed for the user and this command is rather technical
    for orientation in [recent_orientation, old_accepted_orientation, old_orientation_other_state]:
        assert orientation.updated_at != now
