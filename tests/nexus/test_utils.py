from django.utils import timezone
from freezegun import freeze_time

from itou.nexus.enums import Service
from itou.nexus.models import DEFAULT_VALID_SINCE, NexusRessourceSyncStatus
from itou.nexus.utils import complete_full_sync, init_full_sync
from tests.nexus.factories import NexusRessourceSyncStatusFactory


def test_init_full_sync():
    with freeze_time() as frozen_time:
        started_at = init_full_sync(Service.DORA)
        assert started_at == timezone.now()
        # NB: I used timezone.now() because frozen_time().isoformat() is missing the tz

        api_sync = NexusRessourceSyncStatus.objects.get()
        assert api_sync.service == Service.DORA
        assert api_sync.valid_since == DEFAULT_VALID_SINCE
        assert api_sync.in_progress_since == timezone.now()

        # Update existing NexusRessourceSyncStatus
        frozen_time.tick()
        started_at = init_full_sync(Service.DORA)
        assert started_at == timezone.now()

        updated_api_sync = NexusRessourceSyncStatus.objects.get()
        assert updated_api_sync.service == Service.DORA
        assert updated_api_sync.valid_since == DEFAULT_VALID_SINCE
        assert updated_api_sync.in_progress_since == timezone.now()
        assert updated_api_sync.in_progress_since != api_sync.in_progress_since


def test_complete_full_sync():
    start_at = timezone.now()
    NexusRessourceSyncStatusFactory(service=Service.DORA, in_progress_since=start_at)

    assert complete_full_sync(Service.DORA, timezone.now()) is False  # Wrong started_at
    api_synced = NexusRessourceSyncStatus.objects.get()
    assert api_synced.in_progress_since == start_at
    assert complete_full_sync(Service.EMPLOIS, timezone.now()) is False  # Wrong service
    api_synced = NexusRessourceSyncStatus.objects.get()
    assert api_synced.in_progress_since == start_at

    assert complete_full_sync(Service.DORA, start_at) is True
    api_synced = NexusRessourceSyncStatus.objects.get()
    assert api_synced.service == Service.DORA
    assert api_synced.valid_since == start_at
    assert api_synced.in_progress_since is None
