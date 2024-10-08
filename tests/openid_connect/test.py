from functools import wraps

import pytest

from tests.openid_connect.inclusion_connect.test import inclusion_connect_setup
from tests.openid_connect.pro_connect.test import pro_connect_setup


def sso_parametrize(func):
    @pytest.mark.parametrize(
        "sso_setup",
        [inclusion_connect_setup, pro_connect_setup],
        ids=["Inclusion Connect", "ProConnect"],
    )
    @wraps(func)
    def wrapper(*args, **kwargs):
        with kwargs["sso_setup"]():
            return func(*args, **kwargs)

    return wrapper
