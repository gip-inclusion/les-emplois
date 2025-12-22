import random

import pytest
from django.utils import timezone

from itou.nexus.enums import Service
from itou.nexus.models import NexusUser
from itou.nexus.utils import activate_service
from tests.users.factories import PrescriberFactory


def test_activate_service_bad_service():
    user = PrescriberFactory.build()
    for service in Service:
        if service not in [Service.PILOTAGE, Service.MON_RECAP]:
            with pytest.raises(AssertionError):
                activate_service(user, service)


def test_activate_service():
    user = PrescriberFactory(last_login=timezone.now())
    service = random.choice([Service.MON_RECAP, Service.PILOTAGE])
    activate_service(user, service)
    nexus_user = NexusUser.objects.get()
    assert nexus_user.source_id != user.pk
    assert nexus_user.source == service
    assert nexus_user.id == f"{service}--{nexus_user.source_id}"
    assert nexus_user.email == user.email
    assert nexus_user.last_name == user.last_name
    assert nexus_user.first_name == user.first_name
    assert nexus_user.phone == user.phone
    assert nexus_user.auth == ""
    assert nexus_user.kind == ""
    updated_at = nexus_user.updated_at

    # Allow a second call with same email / service to update the user data
    activate_service(user, service)
    nexus_user = NexusUser.objects.get()
    assert nexus_user.updated_at > updated_at
