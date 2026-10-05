import datetime

from django.core.management import call_command
from django.utils import timezone

from itou.insertion.enums import OrientationStatus, OrientationTransition
from itou.insertion.models import OrientationTransitionLog
from tests.insertion.factories import OrientationFactory, ServiceFactory


def test_backfill_orientation_response_delay_migration():
    call_command("migrate", "insertion", "0019", verbosity=0)

    service = ServiceFactory(average_orientation_response_delay_days=16)
    empty_service = ServiceFactory(average_orientation_response_delay_days=80)
    now = timezone.now()
    created_at = now - datetime.timedelta(days=4)
    accepted_at = now - datetime.timedelta(days=1)
    orientation = OrientationFactory(
        service=service,
        status=OrientationStatus.ACCEPTED,
        processing_date=None,
        created_at=created_at,
    )
    OrientationTransitionLog.objects.create(
        orientation=orientation,
        transition=OrientationTransition.ACCEPT,
        from_state=OrientationStatus.PENDING,
        to_state=OrientationStatus.ACCEPTED,
        timestamp=accepted_at,
    )

    call_command("migrate", "insertion", "0020", verbosity=0)

    orientation.refresh_from_db()
    service.refresh_from_db()
    empty_service.refresh_from_db()
    assert orientation.processing_date == accepted_at
    assert service.average_orientation_response_delay_days == 3
    assert empty_service.average_orientation_response_delay_days is None

    call_command("migrate", verbosity=0)
