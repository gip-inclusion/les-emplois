import datetime

import pytest
from freezegun import freeze_time
from jwcrypto import jwt

from itou.nexus.utils import EXPIRY_DELAY, decode_jwt, generate_jwt
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
