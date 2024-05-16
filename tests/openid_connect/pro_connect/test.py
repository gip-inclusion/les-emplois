from functools import wraps

from django.test import override_settings

from itou.openid_connect.pro_connect import constants
from tests.utils.test import TestCase, reload_module


TEST_SETTINGS = {
    "PRO_CONNECT_BASE_URL": "https://pro.connect.fake",
    "PRO_CONNECT_CLIENT_ID": "IC_CLIENT_ID_123",
    "PRO_CONNECT_CLIENT_SECRET": "IC_CLIENT_SECRET_123",
}


@override_settings(**TEST_SETTINGS)
@reload_module(constants)
class ProConnectBaseTestCase(TestCase):
    pass


def override_pro_connect_settings(func):
    @override_settings(**TEST_SETTINGS)
    @reload_module(constants)
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper
