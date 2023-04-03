from functools import wraps

from django.test import override_settings

from itou.utils.test import TestCase, reload_module

from . import constants


TEST_SETTINGS = {
    "INCLUSION_CONNECT_BASE_URL": "https://inclusion.connect.fake",
    "INCLUSION_CONNECT_REALM": "foobar",
    "INCLUSION_CONNECT_CLIENT_ID": "IC_CLIENT_ID_123",
    "INCLUSION_CONNECT_CLIENT_SECRET": "IC_CLIENT_SECRET_123",
}


@override_settings(**TEST_SETTINGS)
@reload_module(constants)
class InclusionConnectBaseTestCase(TestCase):
    pass


def override_inclusion_connect_settings(func):
    @override_settings(**TEST_SETTINGS)
    @reload_module(constants)
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper
