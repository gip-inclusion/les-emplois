import datetime
import random

from django.utils import timezone

from itou.nexus.enums import Service
from itou.nexus.models import DEFAULT_VALID_SINCE, NexusMembership, NexusStructure, NexusUser
from tests.nexus.factories import NexusRessourceSyncStatusFactory, NexusUserFactory


def test_nexus_manager():
    user = NexusUserFactory(with_membership=True)

    # No NexusRessourceSyncStatus all objects are seen by both managers
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 1
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == DEFAULT_VALID_SINCE

    # An NexusRessourceSyncStatus for another service and a temporary NexusRessourceSyncStatus for the same service
    NexusRessourceSyncStatusFactory(service=random.choice([service for service in Service if service != user.source]))
    api_sync = NexusRessourceSyncStatusFactory(
        service=user.source,
        valid_since=timezone.now() - datetime.timedelta(minutes=1),
        new_start_at=timezone.now(),
    )
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 1
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == api_sync.valid_since

    # With a more recent NexusRessourceSyncStatus of the same service only include_old will see the objects
    api_sync.valid_since = timezone.now()
    api_sync.save()
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 0
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == api_sync.valid_since

    # Updating the instance will make the instance available again
    for model in [NexusUser, NexusMembership, NexusStructure]:
        instance = model.include_old.get()
        instance.save(update_fields={"updated_at"})

        assert model.objects.count() == 1
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == api_sync.valid_since
