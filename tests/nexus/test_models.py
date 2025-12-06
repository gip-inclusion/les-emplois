import datetime
import random

from django.utils import timezone

from itou.nexus.enums import Service
from itou.nexus.models import DEFAULT_THRESHOLD, NexusMembership, NexusStructure, NexusUser
from tests.nexus.factories import APIFullSyncFactory, NexusUserFactory


def test_nexus_manager():
    user = NexusUserFactory(with_membership=True)

    # No APIFullSync all objects are seen by both managers
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 1
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == DEFAULT_THRESHOLD

    # An APIFullSync for another service and an temporary APIFullSync for the same service
    APIFullSyncFactory(service=random.choice([service for service in Service if service != user.source]))
    api_sync = APIFullSyncFactory(
        service=user.source,
        timestamp=timezone.now() - datetime.timedelta(minutes=1),
        new_start_at=timezone.now(),
    )
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 1
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == api_sync.timestamp

    # With a more recent APIFullSync of the same service only include_old will see the objects
    api_sync.timestamp = timezone.now()
    api_sync.save()
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 0
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == api_sync.timestamp

    # Updating the instance will make the available again
    for model in [NexusUser, NexusMembership, NexusStructure]:
        instance = model.include_old.get()
        instance.save()

        assert model.objects.count() == 1
        assert model.include_old.count() == 1
        assert model.include_old.with_threshold().get().threshold == api_sync.timestamp
