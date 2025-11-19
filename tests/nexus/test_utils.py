import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from jwcrypto import jwt

from itou.nexus.enums import Service
from itou.nexus.models import User
from itou.nexus.utils import EXPIRY_DELAY, activate_service, decode_jwt, generate_jwt
from tests.users.factories import PrescriberFactory


def test_generate_and_decode_jwt():
    with freeze_time() as frozen_now:
        user = PrescriberFactory()
        token = generate_jwt(user)

        # generated token requires a key to decode
        with pytest.raises(KeyError):
            jwt.JWT(jwt=token).claims

        # It contains the user email
        assert decode_jwt(token) == {"email": user.email}

        # Wait for the JWT to expire, and then extra time for the leeway.
        leeway = 60
        frozen_now.tick(datetime.timedelta(seconds=EXPIRY_DELAY + leeway + 1))
        with pytest.raises(ValueError):
            decode_jwt(token)


def test_activate_service_bad_service():
    user = PrescriberFactory.build()
    for service in Service:
        if service not in [Service.PILOTAGE, Service.MON_RECAP]:
            with pytest.raises(AssertionError):
                activate_service(user, service)


def test_activate_service_mon_recap():
    user = PrescriberFactory(last_login=timezone.now())
    activate_service(user, Service.MON_RECAP)
    nexus_user = User.objects.get()
    assert nexus_user.source_id != user.pk
    assert nexus_user.source == "mon-recap"
    assert nexus_user.id == f"mon-recap--{nexus_user.source_id}"
    assert nexus_user.email == user.email
    assert nexus_user.last_name == user.last_name
    assert nexus_user.first_name == user.first_name
    assert nexus_user.phone == user.phone
    assert nexus_user.auth == ""
    assert nexus_user.kind == ""
    updated_at = nexus_user.updated_at

    # Allow a second call with same email / service to update the user data
    activate_service(user, Service.MON_RECAP)
    nexus_user = User.objects.get()
    assert nexus_user.updated_at > updated_at


def test_activate_service_pilotage():
    user = PrescriberFactory(last_login=timezone.now())
    activate_service(user, Service.PILOTAGE)
    nexus_user = User.objects.get()
    assert nexus_user.source_id == str(user.pk)
    assert nexus_user.source == "pilotage"
    assert nexus_user.id == f"pilotage--{user.pk}"
    assert nexus_user.email == user.email
    assert nexus_user.last_name == user.last_name
    assert nexus_user.first_name == user.first_name
    assert nexus_user.phone == user.phone
    assert nexus_user.auth == ""
    assert nexus_user.kind == ""
    updated_at = nexus_user.updated_at

    # Allow a second call with same email / service to update the user data
    activate_service(user, Service.PILOTAGE)
    nexus_user = User.objects.get()
    assert nexus_user.updated_at > updated_at
